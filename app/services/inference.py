"""Local VLM runtime adapter (docs/architecture.md §10).

The backend never talks to a runtime API outside this module. What is
verified and assumed here is explicit:

- Image input through Ollama's native `/api/chat` with base64 `images` was
  proven on the target hardware in Sprint 1 (docs/runtime-feasibility.md).
- Video input was NEVER verified — `supports_video_input` is False and
  nothing in the app may assume otherwise.
- Capabilities are recorded facts, not guesses from a model name.

Failures are typed (`InferenceError` with stable codes) so routes map them
without knowing the runtime: `inference_unavailable` (503),
`inference_timeout` (504), `inference_invalid_response`,
`inference_empty_response`, `inference_invalid_request`.

The transport is injectable so the test suite runs with no model, no GPU,
and no network.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.config import Settings

DEFAULT_CONTEXT_WINDOW = 8192
HEALTH_TTL_SECONDS = 10.0
HEALTH_TIMEOUT_SECONDS = 2.0
_THINK_FALLBACK_STATUS = 400


class InferenceError(Exception):
    """Typed runtime failure; `code` maps to a stable API error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RuntimeCapabilities:
    runtime_name: str
    model_id: str
    supports_image_input: bool
    supports_video_input: bool
    max_images_per_request: int
    context_window: int


@dataclass(frozen=True)
class InferenceResult:
    answer: str
    model_id: str
    elapsed_seconds: float
    prompt_tokens: int | None = None
    eval_tokens: int | None = None


class InferenceTransport(Protocol):
    """The wire. Injectable so tests fake the runtime entirely."""

    def get_json(self, url: str, timeout_seconds: float) -> tuple[int, dict]: ...

    def post_json(
        self, url: str, payload: dict, timeout_seconds: float
    ) -> tuple[int, dict]: ...

    def close(self) -> None: ...


class HttpxInferenceTransport:
    """Production transport: one pooled httpx client to the loopback runtime."""

    def __init__(self) -> None:
        self._client = httpx.Client()

    def get_json(self, url: str, timeout_seconds: float) -> tuple[int, dict]:
        response = self._client.get(url, timeout=timeout_seconds)
        return response.status_code, response.json()

    def post_json(
        self, url: str, payload: dict, timeout_seconds: float
    ) -> tuple[int, dict]:
        response = self._client.post(url, json=payload, timeout=timeout_seconds)
        return response.status_code, response.json()

    def close(self) -> None:
        self._client.close()


class OllamaInferenceAdapter:
    kind = "ollama"

    def __init__(self, settings: Settings, transport: InferenceTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport or HttpxInferenceTransport()
        self._health_lock = threading.Lock()
        self._health: tuple[str, float] | None = None  # (state, monotonic)

    # --- health -------------------------------------------------------------

    def health_check(self, *, force: bool = False) -> str:
        """`"ready"` or `"unavailable"`, cached briefly so the dashboard's
        2.5 s status poll does not hammer the runtime."""
        with self._health_lock:
            now = time.monotonic()
            if not force and self._health is not None:
                state, at = self._health
                if now - at < HEALTH_TTL_SECONDS:
                    return state
            state = "unavailable"
            try:
                status, _ = self._get_json(
                    self._version_url(), timeout=HEALTH_TIMEOUT_SECONDS
                )
                if status == 200:
                    state = "ready"
            except InferenceError:
                state = "unavailable"
            self._health = (state, now)
            return state

    # --- capabilities ---------------------------------------------------------

    def describe_capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            runtime_name="ollama",
            model_id=self._settings.inference_model,
            supports_image_input=True,  # verified on target hardware (Sprint 1)
            supports_video_input=False,  # never verified — do not assume
            max_images_per_request=self._settings.max_frames_per_request,
            context_window=self._settings.inference_num_ctx,
        )

    # --- generation --------------------------------------------------------------

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[Path],
        timeout_seconds: int | None = None,
        num_ctx: int | None = None,
        think: bool | None = None,
    ) -> InferenceResult:
        """Send prepared prompts plus timestamped still frames. Prompt
        construction is the orchestrator's job (Sprint 10); this layer only
        encodes, transports, and validates."""
        capabilities = self.describe_capabilities()
        if len(image_paths) > capabilities.max_images_per_request:
            raise InferenceError(
                "inference_invalid_request",
                f"Request carries {len(image_paths)} images; the configured "
                f"maximum is {capabilities.max_images_per_request}.",
            )
        images: list[str] = []
        for path in image_paths:
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise InferenceError(
                    "inference_invalid_request",
                    f"Frame file could not be read: {path.name}",
                ) from exc
            if not data:
                raise InferenceError(
                    "inference_invalid_request",
                    f"Frame file is empty: {path.name}",
                )
            images.append(base64.b64encode(data).decode("ascii"))

        payload: dict = {
            "model": self._settings.inference_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt, "images": images},
            ],
            "stream": False,
            "options": {"num_ctx": num_ctx or self._settings.inference_num_ctx},
        }
        if think is not None:
            payload["think"] = think

        url = self._chat_url()
        timeout = timeout_seconds or self._settings.inference_timeout_seconds
        started = time.perf_counter()
        status, body = self._post_json(url, payload, timeout)
        if status == _THINK_FALLBACK_STATUS and "think" in payload:
            # Non-thinking models reject the `think` field; retry without it
            # (same behavior as the Sprint 1 smoke script).
            payload = {k: v for k, v in payload.items() if k != "think"}
            status, body = self._post_json(url, payload, timeout)
        elapsed = time.perf_counter() - started

        if status != 200:
            raise InferenceError(
                "inference_unavailable",
                f"Runtime returned HTTP {status} for a generation request.",
            )
        content = self._extract_content(body)
        return InferenceResult(
            answer=content,
            model_id=self._settings.inference_model,
            elapsed_seconds=elapsed,
            prompt_tokens=body.get("prompt_eval_count"),
            eval_tokens=body.get("eval_count"),
        )

    # --- internals ------------------------------------------------------------

    def _version_url(self) -> str:
        return self._settings.inference_base_url.rstrip("/") + "/api/version"

    def _chat_url(self) -> str:
        return self._settings.inference_base_url.rstrip("/") + "/api/chat"

    def _get_json(self, url: str, timeout: float) -> tuple[int, dict]:
        try:
            return self._transport.get_json(url, timeout)
        except json.JSONDecodeError as exc:
            raise InferenceError(
                "inference_invalid_response",
                "Runtime returned a body that is not valid JSON.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise InferenceError(
                "inference_timeout",
                f"Runtime did not respond within {timeout:g}s.",
            ) from exc
        except httpx.HTTPError as exc:
            raise InferenceError(
                "inference_unavailable",
                f"Runtime is unreachable at {self._settings.inference_base_url}: {exc}",
            ) from exc

    def _post_json(self, url: str, payload: dict, timeout: float) -> tuple[int, dict]:
        try:
            return self._transport.post_json(url, payload, timeout)
        except json.JSONDecodeError as exc:
            raise InferenceError(
                "inference_invalid_response",
                "Runtime returned a body that is not valid JSON.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise InferenceError(
                "inference_timeout",
                f"Runtime did not respond within {timeout:g}s.",
            ) from exc
        except httpx.HTTPError as exc:
            raise InferenceError(
                "inference_unavailable",
                f"Runtime is unreachable at {self._settings.inference_base_url}: {exc}",
            ) from exc

    @staticmethod
    def _extract_content(body: dict) -> str:
        if not isinstance(body, dict):
            raise InferenceError(
                "inference_invalid_response", "Runtime response is not an object."
            )
        message = body.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise InferenceError(
                "inference_invalid_response",
                "Runtime response is missing `message.content`.",
            )
        if not content.strip():
            raise InferenceError(
                "inference_empty_response",
                "Runtime returned an empty answer.",
            )
        return content

    def close(self) -> None:
        self._transport.close()

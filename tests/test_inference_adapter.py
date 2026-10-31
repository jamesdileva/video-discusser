"""Inference adapter — fully mocked transport (no model, no GPU, no network).

Covers the roadmap Sprint 9 gate: typed failures for missing runtime /
timeout / malformed responses, payload shape from the Sprint 1 proven format,
and the video-input assumption guard."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.services.inference import (
    InferenceError,
    OllamaInferenceAdapter,
)

SYSTEM = "You are a video evidence assistant."
USER = "What does the frame show?"


class FakeTransport:
    """Queues (status, body) results or exceptions per call, recording all."""

    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    def _next(self) -> object:
        if not self.results:
            raise AssertionError("FakeTransport ran out of queued results")
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get_json(self, url: str, timeout_seconds: float) -> tuple[int, dict]:
        self.calls.append({"method": "GET", "url": url})
        return self._next()  # type: ignore[return-value]

    def post_json(self, url: str, payload: dict, timeout_seconds: float) -> tuple[int, dict]:
        self.calls.append({"method": "POST", "url": url, "payload": json.loads(json.dumps(payload))})
        return self._next()  # type: ignore[return-value]

    def close(self) -> None:
        self.calls.append({"method": "CLOSE"})


def make_settings(**overrides) -> Settings:
    return Settings(
        inference_model="qwen3.5:4b",
        max_frames_per_request=12,
        inference_num_ctx=8192,
        _env_file=None,  # type: ignore[call-arg]
        **overrides,
    )


def ok_body(content: str = "A red circle on blue.") -> dict:
    return {
        "model": "qwen3.5:4b",
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 330,
        "eval_count": 42,
    }


def test_generate_success_payload_shape(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    transport = FakeTransport([(200, ok_body())])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)

    result = adapter.generate(
        system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame], think=False
    )

    assert result.answer == "A red circle on blue."
    assert result.model_id == "qwen3.5:4b"
    assert result.elapsed_seconds >= 0.0
    assert result.prompt_tokens == 330
    assert result.eval_tokens == 42

    call = transport.calls[0]
    assert call["url"].endswith("/api/chat")
    payload = call["payload"]
    assert payload["model"] == "qwen3.5:4b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"]["num_ctx"] == 8192
    assert payload["messages"][0]["role"] == "system"
    user_msg = payload["messages"][1]
    assert user_msg["content"] == USER
    # The image must be the base64 of the exact file bytes (Sprint 1 format).
    assert user_msg["images"] == [base64.b64encode(b"\xff\xd8fake-jpeg-bytes").decode("ascii")]


def test_think_400_falls_back_without_field(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    transport = FakeTransport([(400, {"error": "does not support thinking"}), (200, ok_body())])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)

    result = adapter.generate(
        system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame], think=True
    )
    assert result.answer.startswith("A red")
    assert len(transport.calls) == 2
    assert "think" in transport.calls[0]["payload"]
    assert "think" not in transport.calls[1]["payload"]


def test_missing_runtime_maps_to_unavailable(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    transport = FakeTransport([httpx.ConnectError("connection refused")])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_unavailable"


def test_timeout_maps_to_inference_timeout(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    transport = FakeTransport([httpx.ReadTimeout("timed out")])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_timeout"


def test_http_500_maps_to_unavailable(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    transport = FakeTransport([(500, {"error": "boom"})])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_unavailable"


def test_non_json_body_is_invalid_response(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")

    class JsonBreaker(FakeTransport):
        def post_json(self, url, payload, timeout_seconds):  # type: ignore[no-untyped-def]
            self.calls.append({"method": "POST", "url": url, "payload": {}})
            raise json.JSONDecodeError("bad", "{", 0)

    adapter = OllamaInferenceAdapter(make_settings(), transport=JsonBreaker([]))
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_invalid_response"


@pytest.mark.parametrize(
    "body",
    [
        {},  # no message at all
        {"message": {}},  # no content
        {"message": {"content": 42}},  # non-string content
        {"choices": [{"message": {"content": "openai-shape"}}]},  # wrong shape
    ],
)
def test_malformed_response_structures(tmp_path: Path, body: dict) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    adapter = OllamaInferenceAdapter(
        make_settings(), transport=FakeTransport([(200, body)])
    )
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_invalid_response"


def test_empty_content_is_empty_response(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    adapter = OllamaInferenceAdapter(
        make_settings(), transport=FakeTransport([(200, ok_body("   "))])
    )
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[frame])
    assert excinfo.value.code == "inference_empty_response"


def test_image_cap_enforced(tmp_path: Path) -> None:
    frames = []
    for i in range(13):  # configured max is 12
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"x")
        frames.append(p)
    adapter = OllamaInferenceAdapter(make_settings(), transport=FakeTransport([]))
    with pytest.raises(InferenceError) as excinfo:
        adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=frames)
    assert excinfo.value.code == "inference_invalid_request"


def test_missing_or_empty_frame_file_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jpg"
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    adapter = OllamaInferenceAdapter(make_settings(), transport=FakeTransport([]))
    for bad in (missing, empty):
        with pytest.raises(InferenceError) as excinfo:
            adapter.generate(system_prompt=SYSTEM, user_prompt=USER, image_paths=[bad])
        assert excinfo.value.code == "inference_invalid_request"


def test_health_check_states_and_ttl() -> None:
    transport = FakeTransport([(200, {"version": "0.40.11"})])
    adapter = OllamaInferenceAdapter(make_settings(), transport=transport)
    assert adapter.health_check() == "ready"
    assert adapter.health_check() == "ready"  # served from TTL cache
    get_calls = [c for c in transport.calls if c["method"] == "GET"]
    assert len(get_calls) == 1  # second call did not re-probe

    dead = FakeTransport([httpx.ConnectError("refused")])
    dead_adapter = OllamaInferenceAdapter(make_settings(), transport=dead)
    assert dead_adapter.health_check(force=True) == "unavailable"


def test_capabilities_never_assume_video_input() -> None:
    """Roadmap Sprint 9: only image input was verified — the adapter must not
    claim video support."""
    adapter = OllamaInferenceAdapter(make_settings(), transport=FakeTransport([]))
    caps = adapter.describe_capabilities()
    assert caps.supports_image_input is True
    assert caps.supports_video_input is False
    assert caps.runtime_name == "ollama"
    assert caps.max_images_per_request == 12

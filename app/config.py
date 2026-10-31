"""Application settings with hard bounds and security validation.

All operational values (ports, paths, frame budgets, timeouts) live here —
nothing else in the codebase may hard-code them. Request-level values must be
clamped to these configured limits (see Sprint 7/10 services), never trusted.

Bounds are conservative starting points from docs/architecture.md §9 to be
validated against the benchmarked runtime profile (docs/runtime-feasibility.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback_host(host: str | None) -> bool:
    """True for loopback hostnames and literal loopback IP literals."""
    if not host:
        return False
    host = host.strip("[]").lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


class Settings(BaseSettings):
    """Validated application settings, loaded from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"

    # --- Backend server -------------------------------------------------
    # Loopback-only by design; see docs/architecture.md §13.
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)

    # --- Inference runtime (Ollama per Sprint 1) ------------------------
    inference_base_url: str = "http://127.0.0.1:11434"
    inference_model: str = "qwen3.5:4b"
    inference_timeout_seconds: int = Field(default=180, ge=5, le=3600)
    max_concurrent_inference: int = Field(default=1, ge=1, le=4)

    # --- Media extraction ------------------------------------------------
    extraction_timeout_seconds: int = Field(default=120, ge=5, le=3600)
    cache_dir: Path = Path("./data/cache")

    # --- Media sources ------------------------------------------------------
    # Semicolon-separated allowlist of directories the local-file source may
    # read from. Browser-supplied paths are only honored inside these roots;
    # the roots themselves come from trusted local configuration. Empty list
    # disables local-file mode.
    local_media_dirs: list[Path] = Field(default_factory=list)
    # Optional YouTube source via yt-dlp. Off by default; downloading must
    # comply with platform terms and applicable law (no DRM circumvention).
    youtube_source_enabled: bool = False
    media_download_timeout_seconds: int = Field(default=600, ge=5, le=3600)

    # --- Frame & window budgets (server clamps requests to these) -------
    analysis_window_seconds: int = Field(default=180, ge=5, le=3600)
    max_frames_per_request: int = Field(default=12, ge=1, le=45)
    frame_sample_interval_seconds: int = Field(default=15, ge=1, le=3600)
    max_frame_dimension: int = Field(default=768, ge=128, le=2048)
    jpeg_quality: int = Field(default=80, ge=1, le=100)

    # --- Input bounds ------------------------------------------------------
    max_question_chars: int = Field(default=2000, ge=1, le=10000)
    max_chat_turns: int = Field(default=8, ge=1, le=50)

    @field_validator("local_media_dirs", mode="before")
    @classmethod
    def _split_local_media_dirs(cls, value: object) -> object:
        """Accept `DIR1;DIR2` (Windows `:` in drive letters rules out commas)."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            parts = (part.strip().strip('"') for part in value.split(";"))
            return [part for part in parts if part]
        return value

    @model_validator(mode="after")
    def _validate_security_and_consistency(self) -> "Settings":
        errors: list[str] = []

        if not _is_loopback_host(self.app_host):
            errors.append(
                f"APP_HOST must be a loopback address (127.0.0.1, localhost, ::1); "
                f"got {self.app_host!r}. This application must not listen on "
                f"LAN interfaces."
            )

        parsed = urlparse(self.inference_base_url)
        if parsed.scheme not in ("http", "https"):
            errors.append(
                f"INFERENCE_BASE_URL must be an http(s) URL; got "
                f"{self.inference_base_url!r}."
            )
        else:
            if not _is_loopback_host(parsed.hostname):
                errors.append(
                    f"INFERENCE_BASE_URL host must be loopback (local-first "
                    f"requirement); got {parsed.hostname!r}."
                )
            if parsed.port == self.app_port:
                errors.append(
                    f"INFERENCE_BASE_URL port ({parsed.port}) must differ from "
                    f"APP_PORT ({self.app_port}); the backend and the model "
                    f"runtime must not share a port."
                )

        if not self.inference_model.strip():
            errors.append("INFERENCE_MODEL must not be empty.")

        if errors:
            raise ValueError(
                "Invalid configuration:\n  - " + "\n  - ".join(errors)
            )
        return self

    def ensure_cache_dir(self) -> Path:
        """Create the cache directory if needed; raise an actionable error if
        it is not usable. Called at startup, not during config parsing."""
        path = self.cache_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"CACHE_DIR {path} cannot be created ({exc}). "
                f"Set CACHE_DIR to a writable path."
            ) from exc
        if not path.is_dir():
            raise RuntimeError(
                f"CACHE_DIR {path} is not a directory. "
                f"Set CACHE_DIR to a writable directory path."
            )
        return path


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor for the running process."""
    return Settings()

"""Configuration validation: hard bounds, loopback enforcement, port collision,
and actionable errors (roadmap Sprint 2 verification)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_are_valid_and_secure() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_host in ("127.0.0.1", "localhost", "::1")
    assert s.app_port == 8000
    assert s.inference_base_url.startswith("http://127.0.0.1")
    # Runtime default must not share the backend port.
    assert ":8000" not in s.inference_base_url
    assert 1 <= s.max_frames_per_request <= 45
    assert 5 <= s.analysis_window_seconds <= 3600


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_non_loopback_app_host_rejected(host: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(app_host=host, _env_file=None)  # type: ignore[call-arg]
    assert "APP_HOST" in str(excinfo.value)


@pytest.mark.parametrize(
    "url", ["http://192.168.1.10:11434", "http://example.com:11434", "ftp://127.0.0.1:11434"]
)
def test_non_loopback_or_bad_scheme_inference_url_rejected(url: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(inference_base_url=url, _env_file=None)  # type: ignore[call-arg]
    assert "INFERENCE_BASE_URL" in str(excinfo.value)


def test_port_collision_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            app_port=11434,
            inference_base_url="http://127.0.0.1:11434",
            _env_file=None,  # type: ignore[call-arg]
        )
    assert "must differ from APP_PORT" in str(excinfo.value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_frames_per_request", 0),
        ("max_frames_per_request", 46),
        ("analysis_window_seconds", 4),
        ("jpeg_quality", 0),
        ("jpeg_quality", 101),
        ("app_port", 0),
        ("app_port", 70000),
        ("max_question_chars", 10001),
        ("max_concurrent_inference", 5),
    ],
)
def test_hard_bounds_enforced(field: str, value: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(**{field: value}, _env_file=None)  # type: ignore[call-arg]
    assert field in str(excinfo.value)


def test_empty_model_name_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(inference_model="   ", _env_file=None)  # type: ignore[call-arg]
    assert "INFERENCE_MODEL" in str(excinfo.value)


def test_ensure_cache_dir_creates_and_reports(tmp_path) -> None:
    s = Settings(cache_dir=tmp_path / "nested" / "cache", _env_file=None)  # type: ignore[call-arg]
    created = s.ensure_cache_dir()
    assert created.is_dir()


def test_ensure_cache_dir_actionable_error(tmp_path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    s = Settings(cache_dir=blocker / "cache", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError) as excinfo:
        s.ensure_cache_dir()
    assert "CACHE_DIR" in str(excinfo.value)

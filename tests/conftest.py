"""Shared fixtures. Tests never require a GPU, network, or the model runtime."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient as _FastAPITestClient

from app.config import Settings
from app.main import create_app


class TestClient(_FastAPITestClient):
    """TestClient presenting a loopback Host, exactly like the real
    deployment. The security middleware (Sprint 13) rejects non-loopback
    Hosts — `testserver` would be rejected as a rebound domain."""

    def __init__(self, app, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs.setdefault("base_url", "http://127.0.0.1:8000")
        super().__init__(app, **kwargs)


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Valid settings isolated from the developer's real `.env` and cache.
    app_env is explicitly development — several test modules exercise the
    dev-only fixture routes deliberately."""
    return Settings(
        app_env="development",
        cache_dir=tmp_path / "cache",
        _env_file=None,  # type: ignore[call-arg]  # ignore any local .env
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=True)

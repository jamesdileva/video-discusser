"""Shared fixtures. Tests never require a GPU, network, or the model runtime."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Valid settings isolated from the developer's real `.env` and cache."""
    return Settings(
        cache_dir=tmp_path / "cache",
        _env_file=None,  # type: ignore[call-arg]  # ignore any local .env
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=True)

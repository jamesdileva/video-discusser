"""The config-driven launcher: host/port come from Settings, never flags."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.config import Settings
import scripts.serve as serve  # noqa: E402


def test_serve_uses_configured_host_and_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict = {}

    def fake_run(app, **kwargs):  # type: ignore[no-untyped-def]
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        serve,
        "get_settings",
        lambda: Settings(app_host="127.0.0.1", app_port=8477, _env_file=None),  # type: ignore[call-arg]
    )

    serve.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8477
    assert captured["app"] == "app.main:app"

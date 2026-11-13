"""Desktop lifecycle (roadmap Sprint 22): backend thread starts, reports
health, and shuts down cleanly on signal — the packaged app's core contract.
No window is opened; pywebview is never required."""

from __future__ import annotations

import threading

from app.config import Settings
from app.desktop import start_backend, stop_backend, wait_for_backend


def make_settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        app_port=8477,
        sessions_dir=tmp_path / "sessions",
        cache_dir=tmp_path / "cache",
        _env_file=None,  # type: ignore[call-arg]
    )


def test_backend_thread_becomes_healthy_and_stops_cleanly(tmp_path) -> None:
    settings = make_settings(tmp_path)
    server = start_backend(settings)
    try:
        # Healthy before the "window" would open.
        assert wait_for_backend(settings.app_port, timeout_seconds=10.0) is True
        # Exactly one backend thread, named and tracked.
        threads = [
            t for t in threading.enumerate() if t.name == "vd-backend" and t.is_alive()
        ]
        assert len(threads) == 1
    finally:
        stop_backend(server)

    # Clean shutdown: the thread joins within the stop budget and the port
    # stops answering (predictable shutdown, roadmap Sprint 22).
    thread = getattr(server, "_vd_thread")
    assert not thread.is_alive()
    assert wait_for_backend(settings.app_port, timeout_seconds=2.0) is False


def test_wait_for_backend_times_out_on_dead_port() -> None:
    assert wait_for_backend(8479, timeout_seconds=0.6) is False

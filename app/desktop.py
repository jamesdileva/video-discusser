"""Desktop entrypoint (roadmap Sprint 22): a native window around the same
loopback backend.

Everything the web dashboard does keeps working — this is the identical
FastAPI app on the identical loopback port, with a WebView2 window in front
of it. Lifecycle contract (roadmap Sprint 22 verification):

- the backend runs in a daemon thread and reports health before the window
  opens;
- closing the window sets `server.should_exit` and the thread joins —
  shutdown is clean, ports and cache are released;
- `--server-only` runs the same lifecycle without a window (used by tests
  and headless verification).

Ollama and model weights are NOT bundled or launched here — they remain a
separate, explicit installation (roadmap constraint). When running frozen
(PyInstaller), backend logs are additionally written to `data/logs/` so the
packaged app's logs stay predictable with no console attached.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import threading
import time
from pathlib import Path

import uvicorn

from app.config import get_settings

LOGGER = logging.getLogger("app.desktop")


def start_backend(settings) -> uvicorn.Server:  # type: ignore[no-untyped-def]
    """Build the app and run uvicorn in a daemon thread; returns the server
    handle so the caller can drive shutdown."""
    from app.main import RequestIdLogFilter, create_app

    app = create_app(settings)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdLogFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    logging.getLogger("uvicorn").handlers = [handler]
    logging.getLogger("uvicorn.access").handlers = [handler]

    config = uvicorn.Config(
        app,
        host=settings.app_host,
        port=settings.app_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="vd-backend", daemon=True)
    thread.start()
    server._vd_thread = thread  # noqa: SLF001 — lifecycle handle for this module
    return server


def wait_for_backend(port: int, *, timeout_seconds: float = 15.0) -> bool:
    """Poll `/api/health` until the backend answers (or timeout)."""
    import httpx

    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.15)
    return False


def stop_backend(server: uvicorn.Server, *, join_seconds: float = 5.0) -> None:
    """Signal shutdown and wait for the backend thread to finish."""
    server.should_exit = True
    thread = getattr(server, "_vd_thread", None)
    if thread is not None:
        thread.join(timeout=join_seconds)


def attach_file_logging(settings) -> Path | None:  # type: ignore[no-untyped-def]
    """Packaged app: mirror backend logs to `data/logs/backend.log` so the
    windowed exe has predictable, inspectable logs with no console."""
    if not getattr(sys, "frozen", False):
        return None
    from app.main import RequestIdLogFilter

    log_dir = Path(settings.cache_dir).parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "backend.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.addFilter(RequestIdLogFilter())
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
        return log_dir / "backend.log"
    except OSError as exc:
        LOGGER.warning("file logging unavailable: %s", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Video Discusser desktop app")
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Run the backend without a window (headless verification).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    log_file = attach_file_logging(settings)

    server = start_backend(settings)
    if not wait_for_backend(settings.app_port):
        stop_backend(server)
        print(
            f"Backend failed to start on http://{settings.app_host}:{settings.app_port} — "
            f"run `python scripts/check_environment.py` for details.",
            file=sys.stderr,
        )
        return 1

    url = f"http://{settings.app_host}:{settings.app_port}/"
    print(f"Video Discusser running at {url} (model runtime must be started separately)")

    try:
        if args.server_only:
            # Headless lifecycle: serve until asked to stop.
            while not server.should_exit:
                time.sleep(0.2)
            stop_backend(server)
            return 0

        # Windowed mode. pywebview is imported lazily so --server-only works
        # without it.
        try:
            import webview
        except ImportError:
            print(
                "pywebview is not installed — open the dashboard in a browser instead, "
                'or `pip install -e ".[desktop]"`.',
                file=sys.stderr,
            )
            stop_backend(server)
            return 1

        webview.create_window(
            "Video Discusser",
            url=url,
            width=1100,
            height=800,
        )
        webview.start()  # blocks until the window is closed
        stop_backend(server)
        if log_file:
            print(f"Backend log: {log_file}")
        return 0
    except KeyboardInterrupt:
        stop_backend(server)
        return 0


if __name__ == "__main__":
    sys.exit(main())

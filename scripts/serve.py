"""Launch the Video Discusser backend with the configured host and port.

Host/port (and every other setting) come from `.env` via `app.config` —
there are no command-line overrides to keep a single source of truth.
The dashboard is served at http://127.0.0.1:<APP_PORT>/ once this runs.

Usage: python scripts/serve.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from app import __version__  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    print(
        f"Starting Video Discusser v{__version__} on "
        f"http://{settings.app_host}:{settings.app_port} — dashboard at / "
        f"(Ctrl+C to stop)"
    )
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    main()

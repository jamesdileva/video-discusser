"""FastAPI application factory.

Boundaries established here:
- Routers own HTTP translation only; services (later sprints) stay HTTP-free.
- Every request gets a request ID, propagated to logs via a context var and
  echoed in the `X-Request-ID` response header.
- Logging discipline (docs/architecture.md §14): lifecycle at INFO; request
  lines at DEBUG so URLs are not logged by default; request bodies, prompts,
  and questions are never logged.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.adapters.local_file_source import LocalFileSource
from app.adapters.media_source import MediaSourceRegistry
from app.adapters.youtube_source import YouTubeSource
from app.api import health, status
from app.api import sync as sync_api
from app.api import frames as frames_api
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.services.active_video import ActiveVideoService
from app.services.frame_extraction import FrameStore

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

LOGGER = logging.getLogger("app")

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class RequestIdLogFilter(logging.Filter):
    """Injects the current request ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Root logging with request-ID-aware formatting. Idempotent."""
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(RequestIdLogFilter())
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(RequestIdLogFilter())
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns (or adopts) a request ID for every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid4().hex
        token = _request_id.set(rid)
        LOGGER.debug("%s %s", request.method, request.url.path)
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. `settings` is injectable for tests; production
    uses the cached `get_settings()`."""
    settings = settings or get_settings()
    configure_logging()
    frame_store = FrameStore(settings.cache_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        cache_dir = settings.ensure_cache_dir()
        loaded = frame_store.load_from_disk()
        LOGGER.info(
            "starting backend v%s env=%s host=%s port=%d cache=%s frames_restored=%d "
            "inference=%s (model configured, not contacted at startup)",
            __version__,
            settings.app_env,
            settings.app_host,
            settings.app_port,
            cache_dir,
            loaded,
            settings.inference_base_url,
        )
        yield
        LOGGER.info("backend stopped")

    app = FastAPI(
        title="Video Discusser",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,  # local single-user app; no need to expose docs UI
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(sync_api.router)
    app.include_router(status.router)
    app.include_router(frames_api.router)
    install_error_handlers(app)
    app.state.active_video = ActiveVideoService()
    app.state.media_sources = MediaSourceRegistry(
        [LocalFileSource(settings), YouTubeSource(settings)]
    )
    app.state.frame_store = frame_store

    if settings.app_env == "development":
        _install_dev_fixture_routes(app)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def _install_dev_fixture_routes(app: FastAPI) -> None:
    """Development-only fixtures for the userscript test harness
    (`/dev-harness.html`). Never registered outside development."""
    browser_dir = Path(__file__).resolve().parent.parent / "browser"

    @app.get("/dev/youtube-sync.user.js", include_in_schema=False)
    async def dev_userscript() -> FileResponse:
        return FileResponse(
            browser_dir / "youtube-sync.user.js", media_type="text/javascript"
        )

    @app.get("/dev/test-clip.mp4", include_in_schema=False)
    async def dev_test_clip() -> FileResponse:
        return FileResponse(
            browser_dir / "fixtures" / "test-clip.mp4", media_type="video/mp4"
        )


app = create_app()

"""Local security middleware (docs/architecture.md §13).

Threat model: the backend binds to loopback only, but anything running in
the same browser can still *send* requests to 127.0.0.1 — drive-by pages,
DNS-rebinding domains. Two checks close those doors:

1. **Host validation** — a rebound domain arrives with a non-loopback Host
   header and is rejected outright. This kills DNS rebinding completely.
2. **Origin validation** — browsers attach an `Origin` to cross-site
   requests. Loopback origins matching this app's port are the dashboard;
   any other origin is rejected *unless* the request carries
   `X-Video-Discusser-Client` — a custom header that browser JS on a hostile
   page cannot send (custom headers force a CORS preflight this server never
   answers) but our extension-privileged userscript can. Same-origin
   requests carry a matching Origin; headerless requests (curl, health
   checks) pass.

Design decisions recorded in the dev log:
- **No CORS middleware on purpose**: emitting no cross-origin headers is
  stricter than any allowlist — cross-origin JS can never read responses.
- **No request token/pairing**: Host + Origin + the preflight-immune marker
  header cover the local threat model without key management.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

CLIENT_MARKER_HEADER = "x-video-discusser-client"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    return hostname.strip("[]").lower().rstrip(".") in _LOOPBACK_HOSTS


class PayloadLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies with a structured 413 before parsing. Bodies
    without Content-Length (chunked) pass — schema validation bounds them and
    the server is loopback-only."""

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request body exceeds {self._max_bytes} bytes.",
                    }
                },
            )
        return await call_next(request)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = settings

    def _allowed_origins(self) -> set[str]:
        port = self._settings.app_port
        return {f"http://{host}:{port}" for host in _LOOPBACK_HOSTS}

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        # 1) Host: the door DNS rebinding walks through.
        host_header = request.headers.get("host", "")
        host_name = urlparse(f"http://{host_header}").hostname if host_header else ""
        if not _is_loopback(host_name):
            return self._forbidden("Unrecognized Host header.")

        # 2) Origin: dashboard origins pass; foreign origins need the marker
        #    that only extension-privileged clients can attach.
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if _is_loopback(parsed.hostname):
                if origin.rstrip("/") not in self._allowed_origins():
                    return self._forbidden("Origin is not an allowed dashboard origin.")
            elif request.headers.get(CLIENT_MARKER_HEADER) is None:
                return self._forbidden("Cross-origin requests require the local companion client.")

        response = await call_next(request)

        # Conservative headers on every response.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            # The dashboard loads only same-origin assets and data.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self'; connect-src 'self'; "
                "script-src 'self'; style-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'",
            )
        return response

    @staticmethod
    def _forbidden(message: str) -> Response:
        """403 in the standard error envelope — security rejections are
        structured like every other API error, never plain text."""
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "forbidden_origin",
                    "message": message,
                }
            },
        )

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
CLIENT_MARKER_VALUE = "userscript"  # presence-only checks are sloppy (audit S8)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    return hostname.strip("[]").lower().rstrip(".") in _LOOPBACK_HOSTS


class PayloadLimitMiddleware:
    """Reject oversized request bodies with a structured 413.

    Pure-ASGI and framing-independent: the body is read and counted up to
    `max_bytes + 1` bytes BEFORE the app sees it, so chunked encoding cannot
    bypass the cap (audit S1) and memory stays bounded regardless of what
    the client declares. Bodies within the limit are replayed to the app.
    GET/HEAD/OPTIONS pass through untouched.
    """

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > self._max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": f"Request body exceeds {self._max_bytes} bytes.",
                        }
                    },
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        full_body = bytes(body)

        async def replay_receive():  # type: ignore[no-untyped-def]
            # Proper ASGI receive: the buffered body once, then a disconnect
            # signal for any further probe.
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return {"type": "http.disconnect"}

        body_sent = False
        await self.app(scope, replay_receive, send)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = settings

    def _allowed_origins(self) -> set[str]:
        port = self._settings.app_port
        # IPv6 literals must be bracketed in origins (audit C8).
        return {
            f"http://{(f'[{h}]' if ':' in h else h)}:{port}"
            for h in _LOOPBACK_HOSTS
        }

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        # 1) Host: the door DNS rebinding walks through. Syntactically
        #    impossible hosts are rejected outright so future parser changes
        #    stay tight (audit S12).
        host_header = request.headers.get("host", "")
        if any(ch in host_header for ch in ("#", "%", ",")) or (
            host_header.count(":") > 1 and not host_header.startswith("[")
        ):
            return self._forbidden("Unrecognized Host header.")
        host_name = urlparse(f"http://{host_header}").hostname if host_header else ""
        if not _is_loopback(host_name):
            return self._forbidden("Unrecognized Host header.")

        # 2) Origin: dashboard origins pass; foreign origins need the marker
        #    with its exact expected value (audit S8 — presence-only checks
        #    accept an empty header, which is meaningless).
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if _is_loopback(parsed.hostname):
                if origin.rstrip("/") not in self._allowed_origins():
                    return self._forbidden("Origin is not an allowed dashboard origin.")
            elif request.headers.get(CLIENT_MARKER_HEADER) != CLIENT_MARKER_VALUE:
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

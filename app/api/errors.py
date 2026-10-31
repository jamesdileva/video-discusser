"""Error plumbing: the `ApiError` exception routes raise, plus handlers that
map every failure to the structured envelope. Unhandled exceptions are logged
server-side with their request ID and echoed as a generic 500 — never with a
stack trace (docs/architecture.md §12)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.errors import ErrorBody, ErrorResponse

LOGGER = logging.getLogger("app.api")


class ApiError(Exception):
    """An expected, structured API failure."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Report which fields failed; never echo the request body itself.
        fields = [
            {"loc": ".".join(str(part) for part in err.get("loc", [])), "msg": err.get("msg", "")}
            for err in exc.errors()[:10]
        ]
        LOGGER.info("request validation failed: %s", fields)
        return error_response(
            422, "validation_error", "Request validation failed.", {"fields": fields}
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("unhandled error")  # server-side only
        return error_response(500, "internal_error", "Internal server error.")

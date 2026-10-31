"""Structured error envelope shared by all API routes.

Every error the dashboard can see has the shape
`{"error": {"code": ..., "message": ..., "details": ...}}` with stable codes
from docs/architecture.md §7. Raw exception details never reach the browser.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody

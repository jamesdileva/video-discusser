"""Health and service-status schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app import __version__


class HealthResponse(BaseModel):
    """`GET /api/health` — must not require the model runtime to be up."""

    status: Literal["ok"] = "ok"
    version: str = __version__


ServiceState = Literal["ready", "unavailable", "not_configured", "unknown"]


class ServiceStates(BaseModel):
    """Per-service readiness, reported separately so the dashboard can explain
    exactly which service is missing (docs/architecture.md §14)."""

    backend: ServiceState = "ready"
    inference: ServiceState = "unknown"
    media_tools: ServiceState = "unknown"


class StatusResponse(BaseModel):
    """`GET /api/status` — populated from Sprint 3 onward; defined now so the
    dashboard and tests share one contract."""

    active_video: object | None = None
    services: ServiceStates = ServiceStates()

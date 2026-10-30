"""Health route — deliberately independent of the model runtime and media
tools so the dashboard can always distinguish "backend up" from other services
(docs/architecture.md §12)."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.schemas.status import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)

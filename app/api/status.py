"""`GET /api/status` — active-video snapshot plus per-service readiness.

Service states are reported separately so the dashboard can explain exactly
which service is missing (docs/architecture.md §14). The inference runtime is
probed only from Sprint 9 onward and stays `unknown` until then; media tools
are checked cheaply via PATH lookup."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends

from app.api.deps import get_active_video_service
from app.schemas.status import ServiceStates, StatusResponse
from app.services.active_video import ActiveVideoService

router = APIRouter(tags=["status"])


@router.get("/api/status", response_model=StatusResponse)
async def get_status(
    service: ActiveVideoService = Depends(get_active_video_service),
) -> StatusResponse:
    ffmpeg_found = shutil.which("ffmpeg") is not None
    return StatusResponse(
        active_video=service.snapshot(),
        services=ServiceStates(
            backend="ready",
            inference="unknown",
            media_tools="ready" if ffmpeg_found else "unavailable",
        ),
    )

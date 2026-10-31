"""`POST /api/sync` — accept pause/manual syncs from the browser userscript.

Untrusted-input rules: the URL is parsed (never string-matched or
shell-interpolated), bounded by the schema, and classified strictly; a
supplied `video_id` must agree with the URL. Success returns the new state
revision. Logs record the video ID and timestamp — never the full URL
(docs/architecture.md §14)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_active_video_service
from app.api.errors import ApiError
from app.schemas.sync import SyncAcceptedResponse, SyncPayload
from app.services.active_video import ActiveVideoService
from app.services.youtube_url import YouTubeUrlError, parse_youtube_url

LOGGER = logging.getLogger("app.sync")

router = APIRouter(tags=["sync"])


@router.post("/api/sync", response_model=SyncAcceptedResponse)
async def post_sync(
    payload: SyncPayload,
    service: ActiveVideoService = Depends(get_active_video_service),
) -> SyncAcceptedResponse:
    try:
        parsed = parse_youtube_url(payload.url)
    except YouTubeUrlError as exc:
        raise ApiError(status_code=422, code=exc.code, message=exc.message) from exc

    if payload.video_id is not None and payload.video_id != parsed.video_id:
        raise ApiError(
            status_code=422,
            code="video_id_mismatch",
            message="Supplied video_id does not match the video ID in the URL.",
        )

    state = service.apply_sync(
        url=payload.url,
        timestamp_seconds=payload.timestamp_seconds,
        video_id=parsed.video_id,
        sync_source=payload.sync_source,
    )
    LOGGER.info(
        "sync accepted revision=%d video_id=%s timestamp=%.2f source=%s",
        state.revision,
        state.video_id,
        state.timestamp_seconds,
        state.sync_source,
    )
    return SyncAcceptedResponse(revision=state.revision, active_video=state)

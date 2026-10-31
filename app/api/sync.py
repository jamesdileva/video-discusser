"""`POST /api/sync` + `POST /api/sync/local-file` — accept pause/manual syncs
from the browser userscript and local-file selections from the dashboard.

Untrusted-input rules: the URL is parsed (never string-matched or
shell-interpolated), bounded by the schema, and classified strictly; a
supplied `video_id` must agree with the URL. Local-file paths are honored
only inside the configured `LOCAL_MEDIA_DIRS` allowlist. Success returns the
new state revision. Logs record the video ID and timestamp — never the full
URL or path (docs/architecture.md §14)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.adapters.media_source import MediaRequest, MediaSourceError
from app.api.deps import get_active_video_service
from app.api.errors import ApiError
from app.schemas.sync import (
    LocalFileSyncPayload,
    SyncAcceptedResponse,
    SyncPayload,
)
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


@router.post("/api/sync/local-file", response_model=SyncAcceptedResponse)
async def post_sync_local_file(
    payload: LocalFileSyncPayload,
    request: Request,
    service: ActiveVideoService = Depends(get_active_video_service),
) -> SyncAcceptedResponse:
    """Sync a local video selected by the local user. The path is resolved
    through the local-file source, which enforces the `LOCAL_MEDIA_DIRS`
    allowlist and probes the file — nothing outside the roots is touched."""
    registry = request.app.state.media_sources
    try:
        resolved = registry.resolve(
            MediaRequest(source_type="local_file", local_path=Path(payload.path))
        )
    except MediaSourceError as exc:
        raise ApiError(status_code=_media_error_status(exc.code), code=exc.code, message=exc.message) from exc

    video_id = "local_" + hashlib.sha256(str(resolved.path).encode("utf-8")).hexdigest()[:12]
    state = service.apply_sync(
        url=str(resolved.path),
        timestamp_seconds=payload.timestamp_seconds,
        video_id=video_id,
        sync_source="manual",
        source="local_file",
        title=resolved.title,
    )
    LOGGER.info(
        "local-file sync accepted revision=%d video_id=%s timestamp=%.2f",
        state.revision,
        state.video_id,
        state.timestamp_seconds,
    )
    return SyncAcceptedResponse(revision=state.revision, active_video=state)


def _media_error_status(code: str) -> int:
    """Map media-source failure codes to HTTP statuses for API surfaces."""
    return {
        "invalid_request": 422,
        "invalid_url": 422,
        "local_path_not_allowed": 422,
        "media_not_found": 422,
        "media_probe_failed": 422,
        "media_source_unavailable": 503,
        "media_tool_missing": 503,
        "media_download_failed": 502,
        "media_download_timeout": 504,
        "process_timeout": 504,
    }.get(code, 500)

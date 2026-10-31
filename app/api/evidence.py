"""`POST /api/evidence/preview` — run the evidence pipeline for the active
video and return servable frame previews, without any model involvement.

This is the dashboard's window into what inference will later receive
(docs/architecture.md §8 workflow B, steps 1-6; the model steps arrive in
Sprints 9-10). Discipline:

- the active-video snapshot (and its revision) is taken up front and the
  response is tagged with it, so a video change during extraction is visible;
- request-level window/frame values are clamped to configured bounds;
- one extraction at a time — a second concurrent request gets a structured
  409 (the full job queue arrives in Sprint 12);
- media/extraction failures map to stable error codes, never raw traces."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.adapters.media_source import MediaRequest, MediaSourceError
from app.api.deps import get_active_video_service
from app.api.errors import ApiError
from app.api.frames import get_frame_store
from app.api.sync import _media_error_status
from app.config import Settings
from app.schemas.discussion import (
    EvidencePreviewRequest,
    EvidencePreviewResponse,
    EvidenceWindow,
    FramePreview,
)
from app.services.active_video import ActiveVideoService
from app.services.frame_extraction import FrameExtractionError, FrameStore, extract_frames
from app.services.frame_sampling import clamp_max_frames, plan_frame_timestamps

LOGGER = logging.getLogger("app.evidence")

router = APIRouter(tags=["evidence"])


def get_evidence_lock(request: Request) -> threading.Lock:
    return request.app.state.evidence_lock


def get_settings_from_state(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/api/evidence/preview", response_model=EvidencePreviewResponse)
async def preview_evidence(
    payload: EvidencePreviewRequest,
    request: Request,
    service: ActiveVideoService = Depends(get_active_video_service),
    store: FrameStore = Depends(get_frame_store),
    lock: threading.Lock = Depends(get_evidence_lock),
    settings: Settings = Depends(get_settings_from_state),
) -> EvidencePreviewResponse:
    snapshot = service.snapshot()
    if snapshot is None:
        raise ApiError(400, "no_active_video", "Sync a video before previewing evidence.")
    if snapshot.source == "youtube":
        media_request = MediaRequest(
            source_type="youtube", url=snapshot.url, video_id=snapshot.video_id
        )
    else:
        media_request = MediaRequest(
            source_type="local_file", local_path=Path(snapshot.url)
        )

    if not lock.acquire(blocking=False):
        raise ApiError(
            409,
            "extraction_in_progress",
            "Another extraction is already running — wait for it to finish.",
        )
    try:
        window_seconds = min(
            payload.window_seconds or settings.analysis_window_seconds,
            settings.analysis_window_seconds,
        )
        max_frames = clamp_max_frames(payload.max_frames, settings.max_frames_per_request)

        registry = request.app.state.media_sources
        try:
            resolved = registry.resolve(media_request)
            plan = plan_frame_timestamps(
                anchor_seconds=snapshot.timestamp_seconds,
                window_seconds=window_seconds,
                max_frames=max_frames,
                duration_seconds=resolved.duration_seconds,
            )
            batch = extract_frames(
                resolved,
                plan,
                settings=settings,
                source_revision=snapshot.revision,
                store=store,
            )
        except MediaSourceError as exc:
            raise ApiError(
                _media_error_status(exc.code), exc.code, exc.message
            ) from exc
        except FrameExtractionError as exc:
            raise ApiError(
                _media_error_status(exc.code), exc.code, exc.message
            ) from exc

        LOGGER.info(
            "evidence preview ready revision=%d video_id=%s frames=%d window=[%.2f, %.2f] cache_hit=%s",
            snapshot.revision,
            snapshot.video_id,
            len(batch.frames),
            plan.window_start_seconds,
            plan.window_end_seconds,
            batch.cache_hit,
        )
        return EvidencePreviewResponse(
            request_id=uuid4().hex,
            cache_key=batch.cache_key,
            snapshot_revision=snapshot.revision,
            video_id=snapshot.video_id,
            source=snapshot.source,
            window=EvidenceWindow(
                start_seconds=plan.window_start_seconds,
                end_seconds=plan.window_end_seconds,
            ),
            frames=[
                FramePreview(
                    frame_id=record.frame_id,
                    timestamp_seconds=record.timestamp_seconds,
                    preview_url=f"/api/frames/{record.frame_id}",
                    width=record.width,
                    height=record.height,
                )
                for record in batch.frames
            ],
            warnings=batch.warnings,
        )
    finally:
        lock.release()

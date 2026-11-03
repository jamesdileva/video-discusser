"""`POST /api/discuss` — the question-to-evidence workflow.

The route is a thin translator: validated payload → `DiscussionService` call
under the shared pipeline lock → response schema; expected service errors map
to stable codes and statuses (docs/architecture.md §7). Inference and media
failures map to *distinct* codes, never a generic 500."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, Request

from app.api.deps import acquire_pipeline
from app.api.errors import ApiError
from app.api.sync import _media_error_status
from app.schemas.discussion import (
    DiscussionRequest,
    DiscussionResponse,
    FrameReference,
)
from app.services.discussion import DiscussionError, DiscussionService

LOGGER = logging.getLogger("app.discussion")

router = APIRouter(tags=["discussion"])

_INFERENCE_STATUS = {
    "inference_unavailable": 503,
    "inference_timeout": 504,
    "inference_invalid_response": 502,
    "inference_empty_response": 502,
}


def get_discussion_service(request: Request) -> DiscussionService:
    return request.app.state.discussion_service


def get_pipeline_lock(request: Request) -> threading.Lock:
    return request.app.state.pipeline_lock


def _error_status(code: str) -> int:
    if code in _INFERENCE_STATUS:
        return _INFERENCE_STATUS[code]
    if code == "no_active_video":
        return 400
    if code == "invalid_question":
        return 422
    return _media_error_status(code)  # media/extraction codes share the mapping


@router.post("/api/discuss", response_model=DiscussionResponse)
async def post_discuss(
    payload: DiscussionRequest,
    lock: threading.Lock = Depends(get_pipeline_lock),
    service: DiscussionService = Depends(get_discussion_service),
) -> DiscussionResponse:
    if not acquire_pipeline(lock):
        raise ApiError(
            409,
            "request_in_progress",
            "Another discussion or extraction is already running — wait for it to finish.",
        )
    try:
        try:
            result = service.discuss(
                question=payload.question,
                window_seconds=payload.window_seconds,
                max_frames=payload.max_frames,
            )
        except DiscussionError as exc:
            raise ApiError(_error_status(exc.code), exc.code, exc.message) from exc
    finally:
        lock.release()

    return DiscussionResponse(
        request_id=result.request_id,
        answer=result.answer,
        video_id=result.video_id,
        source=result.source,
        anchor_timestamp_seconds=result.anchor_timestamp_seconds,
        window_start_seconds=result.window_start_seconds,
        window_end_seconds=result.window_end_seconds,
        frames_used=[
            FrameReference(
                frame_id=record.frame_id,
                timestamp_seconds=record.timestamp_seconds,
                preview_url=f"/api/frames/{record.frame_id}",
                width=record.width,
                height=record.height,
            )
            for record in result.frames
        ],
        warnings=result.warnings,
        snapshot_revision=result.snapshot_revision,
        revision_changed=result.revision_changed,
        model_id=result.model_id,
        elapsed_seconds=result.elapsed_seconds,
    )

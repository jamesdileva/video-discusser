"""Session history routes (roadmap Sprint 15).

History is read-only plus deletion — resuming a historical video as active is
post-MVP. Responses expose video IDs, titles, and frame IDs; stored absolute
paths (local-file mode) are never echoed. Deletion removes the session's
records and any cached frames no longer referenced by other sessions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.services.session_store import SessionStore, SessionStoreError

LOGGER = logging.getLogger("app.sessions")

router = APIRouter(tags=["sessions"])


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def _error_status(code: str) -> int:
    return {"session_not_found": 404, "sessions_disabled": 404}.get(code, 500)


def _map_store_error(exc: SessionStoreError) -> ApiError:
    return ApiError(_error_status(exc.code), exc.code, exc.message)


@router.get("/api/sessions")
def list_sessions(store: SessionStore = Depends(get_session_store)) -> dict:
    return {
        "enabled": store.enabled,
        "sessions": [
            {
                "session_id": s.session_id,
                "video_id": s.video_id,
                "source": s.source,
                "title": s.title,
                "model_id": s.model_id,
                "created_at": s.created_at,
                "last_activity_at": s.last_activity_at,
                "message_count": s.message_count,
            }
            for s in store.list_sessions()
        ],
    }


@router.get("/api/sessions/{session_id}")
def get_session(session_id: str, store: SessionStore = Depends(get_session_store)) -> dict:
    try:
        detail = store.get_session(session_id)
    except SessionStoreError as exc:
        raise _map_store_error(exc) from exc
    return {
        "session": {
            "session_id": detail.summary.session_id,
            "video_id": detail.summary.video_id,
            "source": detail.summary.source,
            "title": detail.summary.title,
            "model_id": detail.summary.model_id,
            "created_at": detail.summary.created_at,
            "message_count": detail.summary.message_count,
        },
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "snapshot_revision": m.snapshot_revision,
                "window": [m.window_start_seconds, m.window_end_seconds],
                "frames": [
                    {
                        "frame_id": f.frame_id,
                        "timestamp_seconds": f.timestamp_seconds,
                        "preview_url": f"/api/frames/{f.frame_id}",
                    }
                    for f in m.frames
                ],
            }
            for m in detail.messages
        ],
    }


@router.delete("/api/sessions/{session_id}")
def delete_session(
    session_id: str,
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> dict:
    try:
        deleted_frame_ids = store.delete_session(session_id)
    except SessionStoreError as exc:
        raise _map_store_error(exc) from exc

    # Cache eligibility: remove frames this session referenced unless another
    # session still references them.
    still_referenced = store.referenced_frame_ids()
    removable = [fid for fid in deleted_frame_ids if fid not in still_referenced]
    removed_files = request.app.state.frame_store.delete_frames(removable)
    LOGGER.info(
        "session deleted id=%s frames_released=%d files_removed=%d",
        session_id,
        len(deleted_frame_ids),
        removed_files,
    )
    return {"deleted": session_id, "frames_removed": removed_files}


@router.delete("/api/sessions")
def clear_sessions(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> dict:
    removed_sessions = store.clear_all()
    # With no sessions left, no frames are referenced by history; the cache
    # itself remains governed by its own age/size policy.
    removed_files = request.app.state.frame_store.delete_frames(
        list(request.app.state.frame_store.registered_frame_ids())
    )
    LOGGER.info("all sessions cleared (%d); cache frames removed=%d", removed_sessions, removed_files)
    return {"cleared_sessions": removed_sessions, "frames_removed": removed_files}

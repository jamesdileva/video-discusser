"""`GET /api/frames/{frame_id}` — serve an application-owned cached frame.

Only IDs present in the `FrameStore` are served, and the resolved path must
stay inside the cache root; unknown or malformed IDs are 404s, never path
probes (docs/architecture.md §7, §13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app.api.errors import ApiError
from app.services.frame_extraction import FRAME_ID_RE, FrameStore

router = APIRouter(tags=["frames"])


def get_frame_store(request: Request) -> FrameStore:
    return request.app.state.frame_store


@router.get("/api/frames/{frame_id}")
def get_frame(
    frame_id: str,
    store: FrameStore = Depends(get_frame_store),
) -> FileResponse:
    if not FRAME_ID_RE.match(frame_id):
        raise ApiError(404, "unknown_frame", "Unknown frame ID.")
    record = store.get(frame_id)
    if record is None:
        raise ApiError(404, "unknown_frame", "Unknown frame ID.")
    path = store.resolve_path(frame_id)
    if path is None or not path.is_file():
        raise ApiError(404, "unknown_frame", "Frame is no longer available.")
    return FileResponse(
        path,
        media_type="image/jpeg",
        # no-store: deleting a session must also end the browser's cached
        # copies of evidence frames (audit S11).
        headers={"Cache-Control": "no-store"},
    )

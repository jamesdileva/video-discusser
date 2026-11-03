"""Discussion/evidence schemas. FrameRecord is the contract shared by
extraction, the preview route, and (later) prompting; the preview response
shapes what the dashboard's evidence card renders."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FrameRecord(BaseModel):
    """One extracted frame (docs/architecture.md §6). `relative_path` is
    relative to the cache root — never an absolute or user-facing path."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    timestamp_seconds: float
    relative_path: str
    width: int
    height: int
    sha256: str
    source_revision: int


class EvidencePreviewRequest(BaseModel):
    """`POST /api/evidence/preview`. Sanity ceilings only — the route clamps
    both values to the server's configured bounds (a request can narrow, but
    never widen, the effective limits)."""

    window_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_frames: int | None = Field(default=None, ge=1, le=10000)


class EvidenceWindow(BaseModel):
    start_seconds: float
    end_seconds: float


class FramePreview(BaseModel):
    frame_id: str
    timestamp_seconds: float
    preview_url: str
    width: int
    height: int


class EvidencePreviewResponse(BaseModel):
    """What the evidence card renders. Tagged with the snapshot revision it
    was built against so the UI can mark it stale when the video changes."""

    request_id: str
    cache_key: str
    snapshot_revision: int
    video_id: str
    source: str
    window: EvidenceWindow
    frames: list[FramePreview]
    warnings: list[str]


class DiscussionRequest(BaseModel):
    """`POST /api/discuss`. Sanity ceilings only — the service clamps to the
    server's configured bounds (`MAX_QUESTION_CHARS`, window, frame cap)."""

    question: str = Field(min_length=1, max_length=10000)
    window_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_frames: int | None = Field(default=None, ge=1, le=10000)


class FrameReference(BaseModel):
    frame_id: str
    timestamp_seconds: float
    preview_url: str
    width: int
    height: int


class DiscussionResponse(BaseModel):
    """`POST /api/discuss` (docs/architecture.md §6). Tagged with the
    snapshot revision the answer was built against; `revision_changed` is
    True when the active video moved on during processing."""

    request_id: str
    answer: str
    video_id: str
    source: str
    anchor_timestamp_seconds: float
    window_start_seconds: float
    window_end_seconds: float
    frames_used: list[FrameReference]
    warnings: list[str]
    snapshot_revision: int
    revision_changed: bool
    model_id: str
    elapsed_seconds: float

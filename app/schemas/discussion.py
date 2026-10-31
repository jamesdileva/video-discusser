"""Discussion/evidence schemas. Populated across Sprints 7-10; FrameRecord is
the contract shared by extraction, the preview route, and (later) prompting."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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

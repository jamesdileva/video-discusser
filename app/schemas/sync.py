"""Sync contract: the payload the browser userscript sends and the immutable
active-video snapshot it produces (docs/architecture.md §6, §7).

Shape-level validation lives here (pydantic); semantic URL classification
(which hosts/paths are supported) lives in `app.services.youtube_url` so the
route can map rejections to precise error codes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_URL_CHARS = 2048

# Standard YouTube video ID alphabet and length.
VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"

SyncSource = Literal["pause_event", "manual"]
VideoSource = Literal["youtube", "local_file"]


class SyncPayload(BaseModel):
    """`POST /api/sync` request body."""

    url: str = Field(min_length=1, max_length=MAX_URL_CHARS)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    video_id: str | None = Field(default=None, pattern=VIDEO_ID_PATTERN)
    sync_source: SyncSource = "pause_event"

    @field_validator("url")
    @classmethod
    def _reject_blank_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("url must not be blank")
        return value


class ActiveVideoState(BaseModel):
    """Immutable snapshot of the currently synced video. Frozen so a snapshot
    handed to a long-running job cannot change underneath it."""

    model_config = ConfigDict(frozen=True)

    video_id: str
    url: str
    source: VideoSource = "youtube"
    timestamp_seconds: float
    updated_at: datetime
    sync_source: SyncSource
    revision: int
    # Reserved: never populated by scraping (architecture.md §6).
    title: str | None = None


class SyncAcceptedResponse(BaseModel):
    """`POST /api/sync` success — the new state revision plus the snapshot."""

    revision: int
    active_video: ActiveVideoState

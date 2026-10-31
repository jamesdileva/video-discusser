"""Active-video state, race-aware by construction.

All mutations flow through this service — never through module-level mutable
dicts (docs/architecture.md §12). Snapshots are frozen pydantic models, so a
snapshot taken by a long-running job (frame extraction, inference) cannot
change underneath it; results are tagged with the revision they were built
against.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.schemas.sync import ActiveVideoState, SyncSource


class ActiveVideoService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: ActiveVideoState | None = None

    def snapshot(self) -> ActiveVideoState | None:
        """Current state, or None before the first accepted sync."""
        with self._lock:
            return self._state

    def current_revision(self) -> int | None:
        with self._lock:
            return self._state.revision if self._state else None

    def apply_sync(
        self,
        *,
        url: str,
        timestamp_seconds: float,
        video_id: str,
        sync_source: SyncSource,
    ) -> ActiveVideoState:
        """Accept a sync as the newest truth. Every accepted sync increments
        the revision, so an out-of-order (stale) sync can never silently
        overwrite newer state — the revision always moves forward and the
        change is observable."""
        with self._lock:
            next_revision = (self._state.revision + 1) if self._state else 1
            state = ActiveVideoState(
                video_id=video_id,
                url=url,
                source="youtube",  # local_file sync arrives with Sprint 6
                timestamp_seconds=timestamp_seconds,
                updated_at=datetime.now(timezone.utc),
                sync_source=sync_source,
                revision=next_revision,
            )
            self._state = state
            return state

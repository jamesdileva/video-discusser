"""Discussion orchestration (docs/architecture.md §8 workflow B/C, §10-11).

One `discuss()` call snapshots the active video, resolves the media source,
plans and extracts (or cache-hits) frames, builds the evidence-aware prompt,
calls the inference adapter, and tags the result with the snapshot revision
it was built against — a video change during processing is reported, never
silently relabeled.

Concurrency: the caller must hold the shared pipeline lock (extraction +
inference are single-job by `MAX_CONCURRENT_INFERENCE=1`); the route acquires
it. All failures are typed (`DiscussionError` or the media/inference errors)
with stable codes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.adapters.media_source import MediaRequest, MediaSourceError
from app.config import Settings
from app.schemas.discussion import FrameRecord
from app.services.active_video import ActiveVideoService
from app.services.frame_extraction import (
    FrameExtractionError,
    FrameStore,
    extract_frames,
)
from app.services.frame_sampling import clamp_max_frames, plan_frame_timestamps
from app.services.inference import InferenceError, OllamaInferenceAdapter
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt

LOGGER = logging.getLogger("app.discussion")


class DiscussionError(Exception):
    """Expected discussion failure with a stable API error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class DiscussionResult:
    request_id: str
    answer: str
    snapshot_revision: int
    revision_changed: bool
    video_id: str
    source: str
    anchor_timestamp_seconds: float
    window_start_seconds: float
    window_end_seconds: float
    frames: list[FrameRecord]
    warnings: list[str] = field(default_factory=list)
    model_id: str = ""
    elapsed_seconds: float = 0.0
    cache_key: str = ""


class DiscussionService:
    def __init__(
        self,
        *,
        settings: Settings,
        active_video: ActiveVideoService,
        media_sources,  # MediaSourceRegistry
        frame_store: FrameStore,
        inference: OllamaInferenceAdapter,
        session_store=None,  # SessionStore | None (Sprint 15)
    ) -> None:
        self._settings = settings
        self._active = active_video
        self._media_sources = media_sources
        self._frame_store = frame_store
        self._inference = inference
        self._session_store = session_store

    def discuss(
        self,
        *,
        question: str,
        window_seconds: int | None = None,
        max_frames: int | None = None,
    ) -> DiscussionResult:
        started = time.perf_counter()
        snapshot = self._active.snapshot()
        if snapshot is None:
            raise DiscussionError(
                "no_active_video", "Sync a video before asking a question."
            )

        cleaned = question.strip()
        if not cleaned:
            raise DiscussionError("invalid_question", "The question must not be empty.")
        if len(cleaned) > self._settings.max_question_chars:
            raise DiscussionError(
                "invalid_question",
                f"The question exceeds the configured maximum of "
                f"{self._settings.max_question_chars} characters.",
            )

        if snapshot.source == "youtube":
            media_request = MediaRequest(
                source_type="youtube", url=snapshot.url, video_id=snapshot.video_id
            )
        else:
            media_request = MediaRequest(source_type="local_file", local_path=Path(snapshot.url))

        window = min(
            window_seconds or self._settings.analysis_window_seconds,
            self._settings.analysis_window_seconds,
        )
        frames_cap = clamp_max_frames(max_frames, self._settings.max_frames_per_request)

        try:
            resolved = self._media_sources.resolve(media_request)
            plan = plan_frame_timestamps(
                anchor_seconds=snapshot.timestamp_seconds,
                window_seconds=window,
                max_frames=frames_cap,
                duration_seconds=resolved.duration_seconds,
            )
            stage_resolve_ms = (time.perf_counter() - started) * 1000
            LOGGER.info(
                "stage=resolve elapsed_ms=%.0f video_id=%s source=%s",
                stage_resolve_ms,
                snapshot.video_id,
                snapshot.source,
            )
            batch = extract_frames(
                resolved,
                plan,
                settings=self._settings,
                source_revision=snapshot.revision,
                store=self._frame_store,
            )
            stage_extract_ms = (time.perf_counter() - started) * 1000 - stage_resolve_ms
            LOGGER.info(
                "stage=extract elapsed_ms=%.0f cache_hit=%s frames=%d",
                stage_extract_ms,
                batch.cache_hit,
                len(batch.frames),
            )
        except MediaSourceError as exc:
            raise DiscussionError(exc.code, exc.message) from exc
        except FrameExtractionError as exc:
            raise DiscussionError(exc.code, exc.message) from exc

        frame_paths = [self._frame_path(record) for record in batch.frames]
        prompt = build_user_prompt(
            question=cleaned,
            source=snapshot.source,
            window_start_seconds=plan.window_start_seconds,
            window_end_seconds=plan.window_end_seconds,
            frame_timestamps=[record.timestamp_seconds for record in batch.frames],
        )
        try:
            result = self._inference.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                image_paths=frame_paths,
                think=self._settings.inference_think_enabled,
            )
        except InferenceError as exc:
            raise DiscussionError(exc.code, exc.message) from exc
        LOGGER.info(
            "stage=infer elapsed_ms=%.0f model=%s",
            (time.perf_counter() - started) * 1000 - stage_extract_ms - stage_resolve_ms,
            result.model_id,
        )

        # Tag, never relabel: if the active video moved on while we worked,
        # the answer still belongs to the snapshot it was built against.
        current = self._active.snapshot()
        revision_changed = bool(current and current.revision != snapshot.revision)

        # Persist the Q/A pair. Recording failures never break the discussion
        # (the store swallows and logs its own errors).
        session_id = None
        if self._session_store is not None:
            session_id = self._session_store.record_discussion(
                video_id=snapshot.video_id,
                video_url=snapshot.url,
                source=snapshot.source,
                title=snapshot.title,
                model_id=result.model_id,
                question=cleaned,
                answer=result.answer,
                snapshot_revision=snapshot.revision,
                window_start_seconds=plan.window_start_seconds,
                window_end_seconds=plan.window_end_seconds,
                frames=list(batch.frames),
            )

        elapsed = time.perf_counter() - started
        LOGGER.info(
            "discussion answered revision=%d video_id=%s frames=%d changed=%s "
            "elapsed=%.1fs prompt_tokens=%s eval_tokens=%s",
            snapshot.revision,
            snapshot.video_id,
            len(batch.frames),
            revision_changed,
            elapsed,
            result.prompt_tokens,
            result.eval_tokens,
        )
        return DiscussionResult(
            request_id=uuid4().hex,
            answer=result.answer,
            snapshot_revision=snapshot.revision,
            revision_changed=revision_changed,
            video_id=snapshot.video_id,
            source=snapshot.source,
            anchor_timestamp_seconds=snapshot.timestamp_seconds,
            window_start_seconds=plan.window_start_seconds,
            window_end_seconds=plan.window_end_seconds,
            frames=list(batch.frames),
            warnings=list(batch.warnings),
            model_id=result.model_id,
            elapsed_seconds=elapsed,
            cache_key=batch.cache_key,
        )

    def _frame_path(self, record: FrameRecord) -> Path:
        path = self._frame_store.resolve_path(record.frame_id)
        if path is None or not path.is_file():
            raise DiscussionError(
                "frame_extraction_failed",
                "A cached frame disappeared before inference could use it.",
            )
        return path

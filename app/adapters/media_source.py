"""Media source contracts (docs/architecture.md §5 adapters).

A `MediaSource` turns a `MediaRequest` into a `ResolvedMedia` — a local file
FFmpeg can read. Source-specific mechanics (allowlists, downloads) live in
the adapters; frame extraction (Sprint 7) is source-agnostic and consumes the
resolved path.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol, runtime_checkable

from app.adapters.subprocess_utils import CommandError, run_command

MediaSourceType = Literal["youtube", "local_file"]


class MediaSourceError(Exception):
    """Expected media-source failure. `code` maps to a stable API error code
    (`422 media_source_unavailable`, … per docs/architecture.md §7)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class MediaRequest:
    """What a caller wants resolved. Only the fields matching `source_type`
    are meaningful; adapters reject mismatched requests."""

    source_type: MediaSourceType
    url: str | None = None
    video_id: str | None = None
    local_path: Path | None = None


@dataclass(frozen=True)
class ResolvedMedia:
    """A concrete, local, readable video."""

    path: Path
    source_type: MediaSourceType
    duration_seconds: float | None
    width: int | None = None
    height: int | None = None
    title: str | None = None
    # Downloaded streams are temporary: callers should delete the file when
    # done unless the user opted into retention.
    cleanup_after_use: bool = False


@runtime_checkable
class MediaSource(Protocol):
    kind: ClassVar[str]

    def supports(self, request: MediaRequest) -> bool: ...

    def resolve(self, request: MediaRequest) -> ResolvedMedia: ...


class MediaSourceRegistry:
    """Picks the adapter for a request. Held on `app.state.media_sources`."""

    def __init__(self, sources: list[MediaSource]) -> None:
        self._sources = list(sources)

    def resolve(self, request: MediaRequest) -> ResolvedMedia:
        for source in self._sources:
            if source.supports(request):
                return source.resolve(request)
        raise MediaSourceError(
            "media_source_unavailable",
            f"No media source is configured for source_type={request.source_type!r}.",
        )


def probe_media(path: Path, *, timeout_seconds: int = 30) -> tuple[float, int | None, int | None]:
    """ffprobe a local video file; return `(duration, width, height)`.

    Raises `MediaSourceError` with actionable codes when FFmpeg is missing or
    the file is not a readable video."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise MediaSourceError(
            "media_tool_missing",
            "ffprobe (FFmpeg) was not found on PATH. Install FFmpeg "
            "(https://ffmpeg.org/download.html or: winget install Gyan.FFmpeg) "
            "and reopen the terminal.",
        )
    args = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = run_command(args, timeout_seconds=timeout_seconds, tool="ffprobe")
    except CommandError as exc:
        raise MediaSourceError(
            "media_probe_failed",
            f"Could not read the video file: {exc.message} {exc.stderr_tail}".strip(),
        ) from exc
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaSourceError(
            "media_probe_failed", "ffprobe returned output that is not valid JSON."
        ) from exc

    duration_raw = data.get("format", {}).get("duration")
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if duration_raw is None or video_stream is None:
        raise MediaSourceError(
            "media_probe_failed",
            "The file is readable but does not look like a video with a duration.",
        )
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError) as exc:
        raise MediaSourceError(
            "media_probe_failed", "ffprobe reported a non-numeric duration."
        ) from exc
    if duration <= 0:
        raise MediaSourceError("media_probe_failed", "The video reports a non-positive duration.")
    return duration, video_stream.get("width"), video_stream.get("height")

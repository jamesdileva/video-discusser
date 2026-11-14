"""Transcript providers (roadmap Sprint 18): time-aligned spoken-content
segments with explicit source attribution.

Two provider tiers, per docs/new-idea.md §4:
1. **Local sidecar subtitles** — `.srt`/`.vtt` next to a local video file
   (user-provided; parsed with the stdlib only).
2. **YouTube captions via yt-dlp** — opt-in (gated like the YouTube source
   adapter), implemented against the documented yt-dlp invocation with an
   injectable runner; requires real verification once yt-dlp is installed.

Local speech-to-text is deliberately NOT here — the roadmap requires STT to
be evaluated separately before it is considered.

Contract: providers return segments fully/overlapping the requested window,
sorted by start time, with a `source` label ("sidecar subtitles" /
"captions"). A missing transcript is `None` — distinct from an error.
Malformed transcript data yields a warning, never a discussion failure.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.adapters.subprocess_utils import CommandError, run_command
from app.config import Settings

LOGGER = logging.getLogger("app.transcripts")

TRANSCRIPT_SOURCE_SIDECAR = "sidecar subtitles"
TRANSCRIPT_SOURCE_CAPTIONS = "captions"


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    # Attribution shown to the model and the user.
    source: str


class TranscriptError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


_TIME_RE = re.compile(
    r"^(?P<h>\d+):(?P<m>\d+):(?P<s>\d+)[,.](?P<ms>\d{1,3})$"
)


def _parse_timestamp(raw: str) -> float:
    """`HH:MM:SS,mmm` or `MM:SS,mmm` → seconds. Raises ValueError on junk."""
    raw = raw.strip().replace(",", ".")
    parts = raw.split(":")
    if len(parts) == 3:
        h, m, rest = parts
    elif len(parts) == 2:
        h, m, rest = "0", parts[0], parts[1]
    else:
        raise ValueError(f"bad timestamp: {raw!r}")
    sec, _, ms = rest.partition(".")
    total = int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")) / 1000
    return total


def _parse_srt(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        # Index line is optional-ish; find the timing line.
        timing_idx = next(
            (i for i, line in enumerate(lines) if "-->" in line), None
        )
        if timing_idx is None:
            continue
        start_raw, _, end_raw = lines[timing_idx].partition("-->")
        start = _parse_timestamp(start_raw.strip().split(" ")[0])
        end = _parse_timestamp(end_raw.strip().split(" ")[0])
        body = "\n".join(lines[timing_idx + 1:]).strip()
        if body:
            segments.append(TranscriptSegment(start, end, body, TRANSCRIPT_SOURCE_SIDECAR))
    return segments


def _parse_vtt(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        timing_idx = next(
            (i for i, line in enumerate(lines) if "-->" in line), None
        )
        if timing_idx is None:
            continue
        start_raw, _, end_raw = lines[timing_idx].partition("-->")
        start = _parse_timestamp(start_raw.strip().split(" ")[0])
        end = _parse_timestamp(end_raw.strip().split(" ")[0])
        body = "\n".join(lines[timing_idx + 1:]).strip()
        if body:
            # VTT cue settings may follow the timestamp on the same line —
            # already stripped by the partition above. Cue identifiers are
            # ignored.
            segments.append(TranscriptSegment(start, end, body, TRANSCRIPT_SOURCE_SIDECAR))
    return segments


def parse_transcript_file(path: Path) -> list[TranscriptSegment]:
    """Parse an SRT or VTT file; raise `TranscriptError` on unreadable or
    malformed content (callers convert to warnings, not failures)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TranscriptError("transcript_unreadable", f"{path.name}: {exc}") from exc
    if not text.strip():
        raise TranscriptError("transcript_empty", f"{path.name} is empty.")
    suffix = path.suffix.lower()
    try:
        if suffix == ".vtt" or text.lstrip().startswith("WEBVTT"):
            segments = _parse_vtt(text)
        else:
            segments = _parse_srt(text)
    except ValueError as exc:
        raise TranscriptError(
            "transcript_malformed", f"{path.name}: {exc}"
        ) from exc
    if not segments:
        raise TranscriptError(
            "transcript_malformed", f"{path.name} contains no readable cues."
        )
    return sorted(segments, key=lambda s: s.start_seconds)


def sidecar_path_for(video_path: Path) -> Path | None:
    """The subtitle sidecar for a local video, if one exists (.srt/.vtt)."""
    for suffix in (".srt", ".vtt"):
        candidate = video_path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _window_overlap(
    segment: TranscriptSegment, window_start: float, window_end: float
) -> bool:
    return segment.end_seconds >= window_start and segment.start_seconds <= window_end


def segments_for_window(
    segments: list[TranscriptSegment],
    window_start: float,
    window_end: float,
    *,
    max_chars: int,
) -> tuple[list[TranscriptSegment], list[str]]:
    """Filter segments to those overlapping the analysis window and enforce
    the character budget (earliest-first, bounded resources). Returns
    (kept_segments, warnings)."""
    warnings: list[str] = []
    overlapping = [
        s for s in segments if _window_overlap(s, window_start, window_end)
    ]
    kept: list[TranscriptSegment] = []
    used = 0
    truncated = False
    for segment in overlapping:
        if used + len(segment.text) > max_chars:
            truncated = True
            break
        kept.append(segment)
        used += len(segment.text)
    if truncated:
        warnings.append(
            f"Transcript truncated at {max_chars} characters — later segments "
            f"in the window were not included."
        )
    return kept, warnings


# --- Local sidecar provider ---------------------------------------------------


def fetch_local_transcript(
    video_path: Path, window_start: float, window_end: float, *, max_chars: int
) -> tuple[list[TranscriptSegment], list[str]] | None:
    """Sidecar `.srt`/`.vtt` next to the video, or None when absent.

    Returns `([], warnings)` when a transcript was attempted but produced
    nothing usable — the warnings surface in the response, not an error."""
    sidecar = sidecar_path_for(video_path)
    if sidecar is None:
        return None
    try:
        segments = parse_transcript_file(sidecar)
    except TranscriptError as exc:
        LOGGER.warning("transcript sidecar ignored: %s", exc.message)
        return [], [f"Transcript file present but unreadable: {exc.message}"]
    kept, warnings = segments_for_window(
        segments, window_start, window_end, max_chars=max_chars
    )
    if not kept:
        return [], warnings or [
            "A transcript file exists but has no lines in the analysis window."
        ]
    return kept, warnings


# --- YouTube captions provider (opt-in, yt-dlp) --------------------------------

_CAPTION_FORMAT_ARGS = [
    "--skip-download",
    "--write-subs",
    "--write-auto-subs",
    "--sub-format",
    "vtt/srt/best",
    "--sub-langs",
    "en.*",
]


def fetch_youtube_transcript(
    url: str,
    video_id: str,
    window_start: float,
    window_end: float,
    *,
    settings: Settings,
    run=None,
) -> tuple[list[TranscriptSegment], list[str]] | None:
    """Captions via yt-dlp (opt-in, yt-dlp required). None when the runtime
    lacks yt-dlp, captions are unavailable, or anything fails — always a
    graceful degradation to the frames-only workflow."""
    ytdlp = shutil.which("yt-dlp")
    if ytdlp is None:
        return [], ["yt-dlp is not installed — captions unavailable."]
    run = run or run_command

    work = Path(settings.cache_dir) / "transcripts"
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [], [f"Transcript cache directory unusable: {exc}"]
    output_base = work / f"cap_{video_id}_{uuid.uuid4().hex[:8]}"

    args = [
        ytdlp,
        "--no-playlist",
        "--no-warnings",
        *_CAPTION_FORMAT_ARGS,
        "-o",
        str(output_base) + ".%(ext)s",
        url,
    ]
    try:
        run(args, timeout_seconds=120, tool="yt-dlp")
    except CommandError as exc:
        return [], [f"Caption fetch failed: {exc.message}"]

    candidates = sorted(work.glob(output_base.name + "*.vtt")) + sorted(
        work.glob(output_base.name + "*.srt")
    )
    if not candidates:
        return [], ["No captions available for this video."]
    try:
        segments = parse_transcript_file(candidates[0])
    except TranscriptError as exc:
        return [], [f"Captions present but unreadable: {exc.message}"]
    kept, warnings = segments_for_window(
        segments,
        window_start,
        window_end,
        max_chars=settings.max_transcript_chars,
    )
    if not kept:
        return [], warnings or [
            "Captions exist but have no lines in the analysis window."
        ]
    relabeled = [
        TranscriptSegment(
            segment.start_seconds,
            segment.end_seconds,
            segment.text,
            TRANSCRIPT_SOURCE_CAPTIONS,
        )
        for segment in kept
    ]
    return relabeled, warnings


def fetch_transcript_for_snapshot(
    *,
    source: str,
    video_path: Path | None,
    url: str | None,
    video_id: str | None,
    window_start: float,
    window_end: float,
    settings: Settings,
    youtube_runner=None,
) -> tuple[list[TranscriptSegment], list[str]] | None:
    """Provider selection by active-video source. Returns None when no
    transcript tier applies or nothing was found (frames-only workflow)."""
    if not settings.transcripts_enabled:
        return None
    if source == "local_file" and video_path is not None:
        return fetch_local_transcript(
            video_path, window_start, window_end, max_chars=settings.max_transcript_chars
        )
    if source == "youtube" and url is not None and video_id is not None:
        if not settings.youtube_source_enabled:
            return None  # captions require the same opt-in as downloads
        return fetch_youtube_transcript(
            url,
            video_id,
            window_start,
            window_end,
            settings=settings,
            run=youtube_runner,
        )
    return None


# --- Prompt rendering -----------------------------------------------------------


def format_transcript_block(segments: list[TranscriptSegment]) -> str:
    """Render segments for the model prompt with time-range attribution."""
    def label(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 60}:{total % 60:02d}"

    lines = [
        f"[{label(s.start_seconds)}-{label(s.end_seconds)}] {s.text}"
        for s in segments
    ]
    source = segments[0].source if segments else "transcript"
    return f"Transcript ({source}):\n" + "\n".join(lines)

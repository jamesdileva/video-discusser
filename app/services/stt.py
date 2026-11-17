"""Local speech-to-text (roadmap Sprint 18b/STT): whisper.cpp transcription
of the analysis window's audio, used ONLY when no transcript tier (sidecar
subtitles / captions) applies — audio processing is opt-in (`STT_ENABLED`)
and entirely local.

Discipline: whisper-cli runs under the same subprocess rules as FFmpeg
(argument arrays, timeout scaled to audio length, bounded stderr, typed
errors). The extracted audio is windowed (bounded by
`STT_MAX_AUDIO_SECONDS`) and temporary. Segments are attributed
`local speech-to-text` — a distinct, lower trust tier than captions or
sidecars (machine transcription may mis-hear; the prompt addendum
discloses this).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from app.adapters.subprocess_utils import CommandError
from app.config import Settings
from app.services.transcripts import TranscriptSegment

LOGGER = logging.getLogger("app.stt")

TRANSCRIPT_SOURCE_STT = "local speech-to-text"

# whisper-cli stdout lines: [00:00:00.000 --> 00:00:07.200]   text
_SEG_RE = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(?P<text>.+)$"
)


class STTError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _hms_to_seconds(raw: str) -> float:
    hours, minutes, sec_ms = raw.split(":")
    seconds, _, ms = sec_ms.partition(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(ms) / 1000


def parse_whisper_stdout(text: str) -> list[TranscriptSegment]:
    """Parse whisper-cli stdout (default timestamped format) into segments."""
    segments: list[TranscriptSegment] = []
    for line in text.splitlines():
        match = _SEG_RE.match(line.strip())
        if not match:
            continue
        body = match.group("text").strip()
        if not body:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=_hms_to_seconds(match.group("start")),
                end_seconds=_hms_to_seconds(match.group("end")),
                text=body,
                source=TRANSCRIPT_SOURCE_STT,
            )
        )
    return segments


def extract_window_audio(
    media_path: Path,
    window_start: float,
    window_duration: float,
    out_path: Path,
    *,
    timeout_seconds: int,
) -> Path:
    """Extract the analysis window's audio as 16 kHz mono WAV via FFmpeg
    (argument arrays, timeout, verified output)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise STTError(
            "media_tool_missing", "ffmpeg was not found on PATH (required for audio extraction)."
        )
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, window_start):.3f}",
        "-t",
        f"{window_duration:.3f}",
        "-i",
        str(media_path),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(out_path),
    ]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise STTError(
            "stt_audio_timeout",
            f"Audio extraction timed out after {timeout_seconds}s.",
        ) from exc
    if completed.returncode != 0:
        raise STTError(
            "stt_audio_failed",
            f"Audio extraction failed: {completed.stderr[-400:]}",
        )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise STTError(
            "stt_audio_failed", "Audio extraction produced no output."
        )
    return out_path


def transcribe(
    audio_path: Path,
    *,
    settings: Settings,
) -> list[TranscriptSegment]:
    """Transcribe a 16 kHz WAV with whisper-cli; parse stdout into
    attributed segments. Raises `STTError` on runtime failures."""
    cli = settings.stt_cli_path
    if not cli.is_file():
        raise STTError(
            "stt_unavailable",
            "whisper-cli was not found at the configured STT_CLI_PATH — "
            "see docs/stt-feasibility.md for setup.",
        )
    model = settings.stt_model_path
    if not model.is_file():
        raise STTError(
            "stt_unavailable",
            f"STT model not found at {model} — download it (see "
            "docs/stt-feasibility.md) or disable STT_ENABLED.",
        )
    args = [
        str(cli),
        "-m",
        str(model),
        "-f",
        str(audio_path),
        "-l",
        "en",
        "-np",
    ]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise STTError("stt_timeout", "Transcription timed out.") from exc
    if completed.returncode != 0:
        raise STTError(
            "stt_failed",
            f"whisper-cli exited with {completed.returncode}: "
            f"{(completed.stderr or '')[-300:]}",
        )
    segments = parse_whisper_stdout(completed.stdout)
    return segments

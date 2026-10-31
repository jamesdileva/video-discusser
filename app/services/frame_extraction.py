"""Frame extraction lifecycle (docs/architecture.md §8 workflow B, §9).

Bounded by construction:
- timestamps come from `frame_sampling` (cap enforced there);
- each frame is a separate FFmpeg invocation with an explicit timeout;
- every output is verified to exist and be non-empty — FFmpeg's exit code is
  never trusted alone;
- metadata (timestamp, generated ID, dimensions, SHA-256) is recorded per
  frame; IDs are generated, never path-derived;
- a cache key over the source identity + plan + settings allows retries and
  re-formatting without re-extraction, and stale entries are swept by age.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.media_source import ResolvedMedia
from app.adapters.subprocess_utils import CommandError, run_command
from app.config import Settings
from app.schemas.discussion import FrameRecord
from app.services.frame_sampling import SamplingPlan

FRAME_ID_RE = re.compile(r"^[0-9a-f]{32}$")

FRAMES_SUBDIR = "frames"
STALE_FRAME_AGE_SECONDS = 24 * 3600


class FrameExtractionError(Exception):
    """Frame extraction failed. `code` maps to a stable API error code
    (`500 frame_extraction_failed`, `media_tool_missing`, …)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ExtractionBatch:
    cache_key: str
    frames: list[FrameRecord]
    warnings: list[str] = field(default_factory=list)
    cache_hit: bool = False


@dataclass(frozen=True)
class _ExtractionInputs:
    """Everything the cache key covers — change any of it and the key changes."""

    source_identity: str
    window_start_seconds: float
    window_end_seconds: float
    timestamps: tuple[float, ...]
    max_frame_dimension: int
    jpeg_quality: int


def compute_cache_key(inputs: _ExtractionInputs) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "source": inputs.source_identity,
            "window": [inputs.window_start_seconds, inputs.window_end_seconds],
            "timestamps": list(inputs.timestamps),
            "max_dim": inputs.max_frame_dimension,
            "quality": inputs.jpeg_quality,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _quality_to_qscale(jpeg_quality: int) -> int:
    """Map configured quality (1-100, higher is better) to FFmpeg's `-q:v`
    for mjpeg (2-31, lower is better)."""
    clamped = max(1, min(100, int(jpeg_quality)))
    return max(2, min(31, round(2 + (100 - clamped) * 29 / 100)))


def _source_identity(resolved: ResolvedMedia) -> str:
    """A stable identity for cache keys without hashing the whole file:
    kind + filename + size + duration."""
    try:
        size = resolved.path.stat().st_size
    except OSError:
        size = -1
    duration = f"{resolved.duration_seconds:.3f}" if resolved.duration_seconds is not None else "?"
    return f"{resolved.source_type}:{resolved.path.name}:{size}:{duration}"


class FrameStore:
    """In-memory index of extracted frames, backed by per-batch JSON metadata
    under `<cache>/frames/` so frames stay servable across restarts."""

    def __init__(self, cache_root: Path) -> None:
        self._cache_root = Path(cache_root)
        self._frames_dir = self._cache_root / FRAMES_SUBDIR
        self._lock = threading.Lock()
        self._records: dict[str, FrameRecord] = {}

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    def register(self, records: list[FrameRecord]) -> None:
        with self._lock:
            for record in records:
                self._records[record.frame_id] = record

    def get(self, frame_id: str) -> FrameRecord | None:
        with self._lock:
            return self._records.get(frame_id)

    def resolve_path(self, frame_id: str) -> Path | None:
        """Absolute path for a known frame, or None. The resolved path must
        stay inside the cache root — a corrupted record can never escape it."""
        record = self.get(frame_id)
        if record is None:
            return None
        candidate = (self._cache_root / record.relative_path).resolve()
        if not candidate.is_relative_to(self._cache_root.resolve()):
            return None
        return candidate

    def load_from_disk(self) -> int:
        """Re-index stored batches after a restart. Returns records loaded."""
        if not self._frames_dir.is_dir():
            return 0
        loaded = 0
        for meta_path in sorted(self._frames_dir.glob("*.json")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                records = [FrameRecord.model_validate(item) for item in data.get("frames", [])]
            except (OSError, ValueError, json.JSONDecodeError):
                continue  # a corrupted batch file must not break startup
            self.register(records)
            loaded += len(records)
        return loaded

    def sweep_stale(self, *, max_age_seconds: int = STALE_FRAME_AGE_SECONDS) -> int:
        """Delete batch metadata (and their frame files) older than the age
        bound. Entries younger than the bound — i.e. anything an in-flight
        request could be using — are never touched. Returns batches removed."""
        if not self._frames_dir.is_dir():
            return 0
        now = time.time()
        removed = 0
        for meta_path in list(self._frames_dir.glob("*.json")):
            try:
                if now - meta_path.stat().st_mtime <= max_age_seconds:
                    continue
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                for item in data.get("frames", []):
                    relative = item.get("relative_path")
                    if isinstance(relative, str):
                        frame_file = (self._cache_root / relative).resolve()
                        if frame_file.is_relative_to(self._cache_root.resolve()) and frame_file.is_file():
                            frame_file.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                with self._lock:
                    for item in data.get("frames", []):
                        self._records.pop(item.get("frame_id"), None)
                removed += 1
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return removed


def extract_frames(
    resolved: ResolvedMedia,
    plan: SamplingPlan,
    *,
    settings: Settings,
    source_revision: int,
    store: FrameStore,
) -> ExtractionBatch:
    """Extract (or reuse) frames for a sampling plan. Raises
    `FrameExtractionError` when the anchor frame cannot be produced; optional
    sample failures become warnings."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FrameExtractionError(
            "media_tool_missing",
            "ffmpeg was not found on PATH. Install FFmpeg and reopen the terminal.",
        )

    inputs = _ExtractionInputs(
        source_identity=_source_identity(resolved),
        window_start_seconds=plan.window_start_seconds,
        window_end_seconds=plan.window_end_seconds,
        timestamps=tuple(plan.timestamps),
        max_frame_dimension=settings.max_frame_dimension,
        jpeg_quality=settings.jpeg_quality,
    )
    cache_key = compute_cache_key(inputs)

    frames_dir = store.frames_dir
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Opportunistic, age-bounded sweep — young entries are never touched.
    store.sweep_stale()

    meta_path = frames_dir / f"{cache_key}.json"
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            records = [FrameRecord.model_validate(item) for item in data.get("frames", [])]
            if records and all(
                (store.resolve_path(record.frame_id) or Path("/dev/null")).is_file()
                for record in records
            ):
                store.register(records)
                return ExtractionBatch(
                    cache_key=cache_key,
                    frames=records,
                    warnings=list(data.get("warnings", [])),
                    cache_hit=True,
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass  # fall through to re-extraction

    warnings: list[str] = []
    records: list[FrameRecord] = []
    qscale = str(_quality_to_qscale(settings.jpeg_quality))
    scale_filter = f"scale=w='min(iw,{settings.max_frame_dimension})':h=-2"

    min_allowed = plan.window_start_seconds
    last_index = len(plan.timestamps) - 1

    for index, requested in enumerate(plan.timestamps):
        is_anchor = index == last_index
        frame_id = uuid4_hex()

        # A stream can end a hair before its container duration; if a seek
        # lands past the last decodable frame, FFmpeg writes nothing. Pull
        # the timestamp back in bounded steps instead of failing, and record
        # the timestamp that actually produced the frame.
        candidates: list[float] = []
        for back in (0.0, 0.25, 0.5):
            candidate = round(
                max(min_allowed, min(requested, plan.window_end_seconds) - back), 3
            )
            if candidate not in candidates:
                candidates.append(candidate)

        record: FrameRecord | None = None
        failures: list[str] = []
        for candidate in candidates:
            output_path = frames_dir / f"{frame_id}.jpg"
            try:
                _extract_single_frame(
                    ffmpeg=ffmpeg,
                    source=resolved.path,
                    timestamp=candidate,
                    output_path=output_path,
                    scale_filter=scale_filter,
                    qscale=qscale,
                    timeout_seconds=settings.extraction_timeout_seconds,
                )
                width, height = _probe_dimensions(output_path)
            except FrameExtractionError as exc:
                failures.append(f"{candidate:.3f}s: {exc.message}")
                continue
            record = FrameRecord(
                frame_id=frame_id,
                timestamp_seconds=candidate,
                relative_path=str(output_path.relative_to(settings.cache_dir)),
                width=width,
                height=height,
                sha256=_sha256(output_path),
                source_revision=source_revision,
            )
            min_allowed = candidate + 0.01  # recorded timestamps stay monotonic
            break

        if record is None:
            detail = f"frame at {requested:.3f}s failed ({'; '.join(failures)})"
            if is_anchor:
                raise FrameExtractionError("frame_extraction_failed", detail)
            warnings.append(detail)
            continue
        records.append(record)

    if not records:
        raise FrameExtractionError(
            "frame_extraction_failed", "No frames could be extracted from the source."
        )

    meta_path.write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "source": inputs.source_identity,
                "window": [plan.window_start_seconds, plan.window_end_seconds],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "warnings": warnings,
                "frames": [record.model_dump() for record in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    store.register(records)
    return ExtractionBatch(cache_key=cache_key, frames=records, warnings=warnings)


def _extract_single_frame(
    *,
    ffmpeg: str,
    source: Path,
    timestamp: float,
    output_path: Path,
    scale_filter: str,
    qscale: str,
    timeout_seconds: int,
) -> None:
    """Extract one JPEG; raise `FrameExtractionError` on any failure — FFmpeg's
    exit code is never trusted alone (output must exist and be non-empty)."""
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        scale_filter,
        "-q:v",
        qscale,
        "-y",
        str(output_path),
    ]
    try:
        run_command(args, timeout_seconds=timeout_seconds, tool="ffmpeg")
    except CommandError as exc:
        raise FrameExtractionError(
            "frame_extraction_failed", f"{exc.message} {exc.stderr_tail}".strip()
        ) from exc
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise FrameExtractionError(
            "frame_extraction_failed",
            "FFmpeg produced no output (seek past the last decodable frame?).",
        )


def _probe_dimensions(path: Path) -> tuple[int, int]:
    """Actual output dimensions via ffprobe — do not assume the scale filter's
    arithmetic."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise FrameExtractionError(
            "media_tool_missing",
            "ffprobe was not found on PATH (ships with FFmpeg).",
        )
    try:
        completed = run_command(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            timeout_seconds=30,
            tool="ffprobe",
        )
        stream = json.loads(completed.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (CommandError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        raise FrameExtractionError(
            "frame_extraction_failed", f"Extracted frame could not be verified: {exc}"
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def uuid4_hex() -> str:
    """Generated frame ID — never derived from URLs or paths."""
    return uuid.uuid4().hex

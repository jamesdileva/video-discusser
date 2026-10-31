"""Frame extraction — integration with real FFmpeg on the committed fixture
clip (10 s, 256×144). Skipped on machines without FFmpeg so the core suite
stays GPU/network/FFmpeg free elsewhere."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.adapters.media_source import ResolvedMedia
from app.config import Settings
from app.services.frame_extraction import (
    FrameExtractionError,
    FrameStore,
    compute_cache_key,
    extract_frames,
)
from app.services.frame_sampling import plan_frame_timestamps

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", _env_file=None, **overrides)  # type: ignore[call-arg]


def resolved_fixture(tmp_path: Path) -> ResolvedMedia:
    """Copy the fixture so cache identities are stable per test."""
    source = tmp_path / "video" / "sample.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_CLIP, source)
    return ResolvedMedia(
        path=source,
        source_type="local_file",
        duration_seconds=10.0,
        width=256,
        height=144,
        title="sample.mp4",
    )


def test_extracts_verified_frames_within_budget(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = resolved_fixture(tmp_path)
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=4, duration_seconds=10.0
    )

    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)

    assert not batch.cache_hit
    assert len(batch.frames) == len(plan.timestamps) <= 4
    assert [f.timestamp_seconds for f in batch.frames] == sorted(
        f.timestamp_seconds for f in batch.frames
    )
    # Frames that extracted on the first seek match the plan exactly; the
    # anchor near EOF may have been pulled back by at most one retry step.
    assert [f.timestamp_seconds for f in batch.frames[:-1]] == plan.timestamps[:-1]
    assert plan.anchor_seconds - 0.5 <= batch.frames[-1].timestamp_seconds <= plan.anchor_seconds
    for record in batch.frames:
        path = store.resolve_path(record.frame_id)
        assert path is not None and path.is_file() and path.stat().st_size > 0
        assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert record.width <= settings.max_frame_dimension
        assert record.source_revision == 1
        # relative to cache root, never absolute
        assert not Path(record.relative_path).is_absolute()


def test_scales_down_large_source_preserving_aspect(tmp_path: Path) -> None:
    big = tmp_path / "video" / "big.mp4"
    big.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=10:duration=3",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(big),
        ],
        check=True,
        timeout=120,
    )
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = ResolvedMedia(
        path=big, source_type="local_file", duration_seconds=3.0, title="big.mp4"
    )
    plan = plan_frame_timestamps(anchor_seconds=3.0, window_seconds=180.0, max_frames=2, duration_seconds=3.0)
    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert batch.frames
    assert all(record.width == 768 for record in batch.frames)
    assert all(record.height == 432 for record in batch.frames)  # 16:9 preserved


def test_anchor_at_eof_is_clamped_and_extracts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = resolved_fixture(tmp_path)
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=1, duration_seconds=10.0
    )
    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert len(batch.frames) == 1
    # The clip's last decodable frame is at 9.9s; the anchor lands within one
    # retry step of the clamped request and the frame is real.
    recorded = batch.frames[0].timestamp_seconds
    assert 9.4 <= recorded <= 9.95
    assert store.resolve_path(batch.frames[0].frame_id).is_file()


def test_corrupt_source_returns_clear_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    bogus = tmp_path / "video" / "bogus.mp4"
    bogus.parent.mkdir(parents=True, exist_ok=True)
    bogus.write_text("this is not a video", encoding="utf-8")
    resolved = ResolvedMedia(
        path=bogus, source_type="local_file", duration_seconds=10.0, title="bogus.mp4"
    )
    plan = plan_frame_timestamps(anchor_seconds=5.0, window_seconds=180.0, max_frames=2)
    with pytest.raises(FrameExtractionError) as excinfo:
        extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert excinfo.value.code == "frame_extraction_failed"


def test_cache_hit_avoids_reextraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = resolved_fixture(tmp_path)
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=3, duration_seconds=10.0
    )

    first = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert not first.cache_hit

    import app.services.frame_extraction as fe

    calls = {"n": 0}
    real_run = fe.run_command

    def counting_run(*args, **kwargs):
        calls["n"] += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(fe, "run_command", counting_run)
    second = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert second.cache_hit
    assert calls["n"] == 0  # no FFmpeg/ffprobe invocations on the cache path
    assert [f.frame_id for f in second.frames] == [f.frame_id for f in first.frames]


def test_cache_key_changes_when_settings_change(tmp_path: Path) -> None:
    from app.services.frame_extraction import _ExtractionInputs

    base = _ExtractionInputs(
        source_identity="local_file:sample.mp4:27119:10.000",
        window_start_seconds=0.0,
        window_end_seconds=10.0,
        timestamps=(0.0, 5.0, 10.0),
        max_frame_dimension=768,
        jpeg_quality=80,
    )

    def key_with(**changes) -> str:
        fields = {
            "source_identity": base.source_identity,
            "window_start_seconds": base.window_start_seconds,
            "window_end_seconds": base.window_end_seconds,
            "timestamps": base.timestamps,
            "max_frame_dimension": base.max_frame_dimension,
            "jpeg_quality": base.jpeg_quality,
            **changes,
        }
        return compute_cache_key(_ExtractionInputs(**fields))

    baseline = key_with()
    assert baseline == key_with()  # deterministic
    assert key_with(max_frame_dimension=512) != baseline
    assert key_with(jpeg_quality=70) != baseline
    assert key_with(timestamps=(0.0, 5.0, 9.0)) != baseline
    assert key_with(source_identity="local_file:other.mp4:1:10.000") != baseline


def test_stale_sweep_removes_only_old_batches(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = resolved_fixture(tmp_path)
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=2, duration_seconds=10.0
    )
    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)

    # Backdate the batch metadata beyond the stale bound.
    meta = next((settings.cache_dir / "frames").glob("*.json"))
    old = meta.stat().st_mtime - (25 * 3600)
    import os

    os.utime(meta, (old, old))

    removed = store.sweep_stale()
    assert removed == 1
    assert store.get(batch.frames[0].frame_id) is None
    assert not meta.exists()
    for record in batch.frames:
        assert not (settings.cache_dir / record.relative_path).exists()

    # A fresh batch survives the sweep.
    fresh_batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    assert store.sweep_stale() == 0
    assert store.get(fresh_batch.frames[0].frame_id) is not None


def test_store_reloads_from_disk_after_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = FrameStore(settings.cache_dir)
    resolved = resolved_fixture(tmp_path)
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=2, duration_seconds=10.0
    )
    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)

    fresh_store = FrameStore(settings.cache_dir)  # simulates a restarted process
    assert fresh_store.get(batch.frames[0].frame_id) is None
    loaded = fresh_store.load_from_disk()
    assert loaded >= 1
    record = fresh_store.get(batch.frames[0].frame_id)
    assert record is not None
    assert fresh_store.resolve_path(record.frame_id).is_file()

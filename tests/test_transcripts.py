"""Transcript parsing and providers (roadmap Sprint 18): SRT/VTT parsing,
window filtering, character budget, sidecar discovery, and the graceful
degradation contract."""

from __future__ import annotations

from pathlib import Path

import shutil

import pytest

from app.services.transcripts import (
    TRANSCRIPT_SOURCE_CAPTIONS,
    TRANSCRIPT_SOURCE_SIDECAR,
    TranscriptError,
    fetch_local_transcript,
    fetch_youtube_transcript,
    format_transcript_block,
    parse_transcript_file,
    segments_for_window,
    sidecar_path_for,
)

SRT = """1
00:00:01,000 --> 00:00:03,500
Welcome to Gate Seven.

2
00:00:04,000 --> 00:00:06,000
Please have your boarding passes ready.

3
00:00:20,000 --> 00:00:22,000
This line is outside the window.
"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.500
Welcome to Gate Seven.

cue-with-id
00:00:04.000 --> 00:00:06.000 position:50%
Please have your boarding passes ready.
"""


@pytest.mark.parametrize(
    ("text", "expected_count"),
    [(SRT, 3), (VTT, 2)],
)
def test_parses_srt_and_vtt(tmp_path: Path, text: str, expected_count: int) -> None:
    f = tmp_path / ("sample" + (".srt" if text is SRT else ".vtt"))
    f.write_text(text, encoding="utf-8")
    segments = parse_transcript_file(f)
    assert len(segments) == expected_count
    assert segments[0].start_seconds == pytest.approx(1.0)
    assert segments[0].text == "Welcome to Gate Seven."
    assert segments[0].source == TRANSCRIPT_SOURCE_SIDECAR


def test_sidecar_discovery_prefers_srt(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"x")
    assert sidecar_path_for(video) is None
    (tmp_path / "sample.vtt").write_text(VTT, encoding="utf-8")
    assert sidecar_path_for(video).suffix == ".vtt"
    (tmp_path / "sample.srt").write_text(SRT, encoding="utf-8")
    assert sidecar_path_for(video).suffix == ".srt"


def test_malformed_and_empty_transcripts_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "a.srt"
    empty.write_text("", encoding="utf-8")
    junk = tmp_path / "b.srt"
    junk.write_text("this is not a subtitle file\nat all\n", encoding="utf-8")
    bad_ts = tmp_path / "c.srt"
    bad_ts.write_text(
        "1\nnot:a:timestamp --> also:bad:stamp\nhello\n", encoding="utf-8"
    )
    for f in (empty, junk, bad_ts):
        with pytest.raises(TranscriptError):
            parse_transcript_file(f)


def test_window_filter_and_char_budget() -> None:
    # Build segments directly for deterministic math.
    from app.services.transcripts import TranscriptSegment

    segs = [
        TranscriptSegment(1.0, 3.5, "a" * 10, TRANSCRIPT_SOURCE_SIDECAR),
        TranscriptSegment(4.0, 6.0, "b" * 10, TRANSCRIPT_SOURCE_SIDECAR),
        TranscriptSegment(20.0, 22.0, "c" * 10, TRANSCRIPT_SOURCE_SIDECAR),  # outside
    ]
    kept, warnings = segments_for_window(segs, 0.0, 10.0, max_chars=1000)
    assert [s.text for s in kept] == ["a" * 10, "b" * 10]
    assert warnings == []

    kept2, warnings2 = segments_for_window(segs, 0.0, 10.0, max_chars=15)
    assert [s.text for s in kept2] == ["a" * 10]  # earliest-first, budget-bound
    assert len(warnings2) == 1 and "truncated" in warnings2[0]


def _write(directory: Path, text: str, name: str) -> Path:
    f = directory / name
    f.write_text(text, encoding="utf-8")
    return f


def test_local_fetch_missing_sidecar_is_none(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"x")
    assert fetch_local_transcript(video, 0.0, 10.0, max_chars=1000) is None


def test_local_fetch_unreadable_sidecar_warns_not_fails(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"x")
    sidecar = tmp_path / "sample.srt"
    sidecar.write_text("", encoding="utf-8")
    result = fetch_local_transcript(video, 0.0, 10.0, max_chars=1000)
    assert result is not None
    segments, warnings = result
    assert segments == []
    assert any("unreadable" in w for w in warnings)


def test_format_block_attributions_and_ranges() -> None:
    from app.services.transcripts import TranscriptSegment

    segments = [
        TranscriptSegment(61.0, 63.5, "hello", TRANSCRIPT_SOURCE_SIDECAR),
    ]
    block = format_transcript_block(segments)
    assert block.startswith("Transcript (sidecar subtitles):")
    assert "[1:01-1:03] hello" in block


def test_youtube_provider_requires_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without yt-dlp the provider degrades gracefully (None + warning)."""
    monkeypatch.setattr(
        "app.services.transcripts.find_ytdlp", lambda: None
    )
    from app.config import Settings
    from app.services.transcripts import fetch_youtube_transcript

    settings = Settings(
        youtube_source_enabled=True, cache_dir=tmp_path / "cache", _env_file=None  # type: ignore[call-arg]
    )
    result = fetch_youtube_transcript(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
        0.0,
        10.0,
        settings=settings,
    )
    assert result is not None  # (None, warnings) tuple
    segments, warnings = result
    assert segments == []
    assert any("yt-dlp is not installed" in w for w in warnings)


def test_youtube_provider_relabels_captions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a fake runner producing a VTT, segments are relabeled as captions
    (source attribution distinguishes them from sidecar subtitles)."""
    from app.config import Settings
    from app.services.transcripts import fetch_youtube_transcript

    settings = Settings(
        youtube_source_enabled=True, cache_dir=tmp_path / "cache", _env_file=None  # type: ignore[call-arg]
    )
    monkeypatch.setattr(
        "app.services.transcripts.find_ytdlp", lambda: "C:/fake/yt-dlp.exe"
    )

    def fake_run(args, *, timeout_seconds, tool):  # type: ignore[no-untyped-def]
        out_base = Path(args[args.index("-o") + 1]).with_suffix("")
        out_base = Path(str(out_base).replace("%(ext)s", ""))
        vtt = out_base.with_suffix(".en.vtt")
        vtt.write_text(VTT, encoding="utf-8")
        return None

    result = fetch_youtube_transcript(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
        0.0,
        10.0,
        settings=settings,
        run=fake_run,
    )
    assert result is not None
    segments, warnings = result
    assert len(segments) == 2
    assert all(s.source == TRANSCRIPT_SOURCE_CAPTIONS for s in segments)
    assert warnings == []

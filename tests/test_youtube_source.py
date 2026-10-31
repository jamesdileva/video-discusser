"""YouTube source adapter: opt-in gating, URL validation before any external
tool, typed failures, and a faked successful download (yt-dlp is not
installed on the dev machine — the runner seam is faked; a real download is
exercised only when the feature is used)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.adapters.media_source import MediaRequest, MediaSourceError
from app.adapters.subprocess_utils import CommandError
from app.adapters.youtube_source import YouTubeSource
from app.config import Settings

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def make_settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        youtube_source_enabled=enabled,
        cache_dir=tmp_path / "cache",
        _env_file=None,  # type: ignore[call-arg]
    )


class RecordingRunner:
    """Stands in for run_command; can fake a download or a failure."""

    def __init__(self, *, fail: CommandError | None = None, fake_download: bool = True) -> None:
        self.calls: list[dict] = []
        self.fail = fail
        self.fake_download = fake_download

    def __call__(self, args: list[str], *, timeout_seconds: int, tool: str):
        assert isinstance(args, list) and all(isinstance(a, str) for a in args), (
            "commands must be argument arrays"
        )
        self.calls.append({"args": list(args), "timeout_seconds": timeout_seconds, "tool": tool})
        if self.fail is not None:
            raise self.fail
        if self.fake_download:
            out_base = Path(args[args.index("-o") + 1]).with_suffix("")  # strip %(ext)s template
            out_base = Path(str(out_base).replace("%(ext)s", ""))
            shutil.copy(FIXTURE_CLIP, out_base.with_suffix(".mp4"))
        return None


@pytest.fixture
def fake_ytdlp(monkeypatch: pytest.MonkeyPatch) -> None:
    """yt-dlp is not installed on this machine; tests that exercise the runner
    stub the binary lookup so they are machine-independent. Only the yt-dlp
    lookup is faked — `shutil` is a shared module, so other tools (ffprobe)
    must resolve normally."""
    real_which = shutil.which
    monkeypatch.setattr(
        "app.adapters.youtube_source.shutil.which",
        lambda name, **kwargs: "C:/fake/yt-dlp.exe" if name == "yt-dlp" else real_which(name, **kwargs),
    )


def test_disabled_by_default(tmp_path: Path) -> None:
    runner = RecordingRunner()
    source = YouTubeSource(make_settings(tmp_path, enabled=False), run=runner)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))
    assert excinfo.value.code == "media_source_unavailable"
    assert "YOUTUBE_SOURCE_ENABLED" in excinfo.value.message
    assert runner.calls == []  # nothing external was invoked


def test_unsupported_url_rejected_before_external_tools(tmp_path: Path) -> None:
    runner = RecordingRunner()
    source = YouTubeSource(make_settings(tmp_path), run=runner)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(
            MediaRequest(source_type="youtube", url="https://evil.com/watch?v=dQw4w9WgXcQ")
        )
    assert excinfo.value.code == "invalid_url"
    assert runner.calls == []  # rejected before yt-dlp is even looked up


def test_missing_ytdlp_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.youtube_source.shutil.which", lambda name: None)
    source = YouTubeSource(make_settings(tmp_path), run=RecordingRunner())
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))
    assert excinfo.value.code == "media_tool_missing"
    assert "local-file mode" in excinfo.value.message


def test_ytdlp_failure_maps_to_typed_error(tmp_path: Path, fake_ytdlp: None) -> None:
    runner = RecordingRunner(
        fail=CommandError(
            "process_failed",
            "yt-dlp exited with code 1.",
            returncode=1,
            stderr_tail="ERROR: Sign in to confirm you're not a bot.",
        )
    )
    source = YouTubeSource(make_settings(tmp_path), run=runner)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))
    assert excinfo.value.code == "media_download_failed"
    assert "Sign in" in excinfo.value.message  # bounded stderr surfaces for diagnosis


def test_download_timeout_maps_to_distinct_code(tmp_path: Path, fake_ytdlp: None) -> None:
    runner = RecordingRunner(
        fail=CommandError("process_timeout", "yt-dlp timed out after 600s and was terminated.")
    )
    settings = make_settings(tmp_path)
    source = YouTubeSource(settings, run=runner)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))
    assert excinfo.value.code == "media_download_timeout"


def test_successful_download_resolves_and_probes(tmp_path: Path, fake_ytdlp: None) -> None:
    runner = RecordingRunner()
    settings = make_settings(tmp_path)
    source = YouTubeSource(settings, run=runner)
    resolved = source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))

    assert resolved.source_type == "youtube"
    assert resolved.cleanup_after_use is True  # downloads are temporary
    assert resolved.duration_seconds == pytest.approx(10.0, abs=1.0)
    assert resolved.path.is_file()
    assert resolved.path.parent.name == "downloads"
    assert resolved.path.name.startswith("yt_dQw4w9WgXcQ_")
    # Output name is generated — never URL-derived beyond the verified ID.
    assert "watch" not in resolved.path.name

    run = runner.calls[0]
    assert run["timeout_seconds"] == settings.media_download_timeout_seconds
    assert run["tool"] == "yt-dlp"
    args = run["args"]
    assert "--no-playlist" in args
    assert VALID_URL in args  # URL passed as a single argv element


def test_no_output_file_after_success_is_typed_error(tmp_path: Path, fake_ytdlp: None) -> None:
    runner = RecordingRunner(fake_download=False)
    source = YouTubeSource(make_settings(tmp_path), run=runner)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube", url=VALID_URL))
    assert excinfo.value.code == "media_download_failed"


def test_missing_url_rejected(tmp_path: Path) -> None:
    source = YouTubeSource(make_settings(tmp_path), run=RecordingRunner())
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="youtube"))
    assert excinfo.value.code == "invalid_request"

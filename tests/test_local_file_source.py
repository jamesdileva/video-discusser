"""Local-file media source: allowlist enforcement, probing with the real
committed fixture clip, and typed failures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.adapters.local_file_source import LocalFileSource
from app.adapters.media_source import (
    MediaRequest,
    MediaSourceError,
    MediaSourceRegistry,
)
from app.config import Settings
from app.main import create_app

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "videos"
    root.mkdir()
    shutil.copy(FIXTURE_CLIP, root / "sample.mp4")
    return root


@pytest.fixture
def source(media_root: Path) -> LocalFileSource:
    settings = Settings(local_media_dirs=[media_root], _env_file=None)  # type: ignore[call-arg]
    return LocalFileSource(settings)


def test_resolves_and_probes_sample_video(source: LocalFileSource, media_root: Path) -> None:
    resolved = source.resolve(
        MediaRequest(source_type="local_file", local_path=media_root / "sample.mp4")
    )
    assert resolved.path.is_file()
    assert resolved.source_type == "local_file"
    # The committed fixture clip is a 10-second 256x144 testsrc render.
    assert resolved.duration_seconds == pytest.approx(10.0, abs=1.0)
    assert (resolved.width, resolved.height) == (256, 144)
    assert resolved.cleanup_after_use is False
    assert resolved.title == "sample.mp4"


def test_resolves_file_in_subdirectory_of_root(source: LocalFileSource, media_root: Path) -> None:
    sub = media_root / "nested"
    sub.mkdir()
    shutil.copy(FIXTURE_CLIP, sub / "clip.mp4")
    resolved = source.resolve(
        MediaRequest(source_type="local_file", local_path=sub / "clip.mp4")
    )
    assert resolved.path.is_file()


def test_path_outside_allowlist_rejected(source: LocalFileSource, tmp_path: Path) -> None:
    outsider = tmp_path / "elsewhere.mp4"
    shutil.copy(FIXTURE_CLIP, outsider)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="local_file", local_path=outsider))
    assert excinfo.value.code == "local_path_not_allowed"


def test_traversal_via_relative_path_rejected(source: LocalFileSource, tmp_path: Path) -> None:
    # A relative path that escapes a root after resolution must be rejected.
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(
            MediaRequest(
                source_type="local_file",
                local_path=Path("..") / ".." / "Windows" / "win.ini",
            )
        )
    assert excinfo.value.code == "local_path_not_allowed"


def test_missing_file_rejected(source: LocalFileSource, media_root: Path) -> None:
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(
            MediaRequest(source_type="local_file", local_path=media_root / "nope.mp4")
        )
    assert excinfo.value.code == "media_not_found"


def test_disabled_without_configured_roots(tmp_path: Path) -> None:
    settings = Settings(local_media_dirs=[], _env_file=None)  # type: ignore[call-arg]
    source = LocalFileSource(settings)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(
            MediaRequest(source_type="local_file", local_path=tmp_path / "sample.mp4")
        )
    assert excinfo.value.code == "media_source_unavailable"
    assert "LOCAL_MEDIA_DIRS" in excinfo.value.message


def test_non_video_file_rejected_with_clear_error(source: LocalFileSource, media_root: Path) -> None:
    text_file = media_root / "notes.txt"
    text_file.write_text("this is not a video", encoding="utf-8")
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="local_file", local_path=text_file))
    assert excinfo.value.code == "media_probe_failed"


def test_missing_local_path_rejected(source: LocalFileSource) -> None:
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="local_file"))
    assert excinfo.value.code == "invalid_request"


def test_registry_wired_into_app(media_root: Path) -> None:
    settings = Settings(
        local_media_dirs=[media_root],
        cache_dir=media_root.parent / "cache",
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app(settings)
    registry: MediaSourceRegistry = app.state.media_sources
    resolved = registry.resolve(
        MediaRequest(source_type="local_file", local_path=media_root / "sample.mp4")
    )
    assert resolved.duration_seconds == pytest.approx(10.0, abs=1.0)


def test_registry_rejects_unconfigured_source_type(tmp_path: Path) -> None:
    registry = MediaSourceRegistry([])  # nothing configured
    with pytest.raises(MediaSourceError) as excinfo:
        registry.resolve(MediaRequest(source_type="youtube", url="https://youtu.be/dQw4w9WgXcQ"))
    assert excinfo.value.code == "media_source_unavailable"

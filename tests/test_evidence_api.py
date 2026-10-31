"""`POST /api/sync/local-file` and `POST /api/evidence/preview` — the Sprint 8
evidence workflow. Extraction tests use real FFmpeg (skipped without it)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)


def make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    media_root = tmp_path / "videos"
    media_root.mkdir()
    shutil.copy(FIXTURE_CLIP, media_root / "sample.mp4")
    settings = Settings(
        cache_dir=tmp_path / "cache",
        local_media_dirs=[media_root],
        _env_file=None,  # type: ignore[call-arg]
    )
    return TestClient(create_app(settings)), media_root


def error_code(resp) -> str:
    body = resp.json()
    assert "error" in body, body
    return body["error"]["code"]


def test_local_file_sync_creates_active_video(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    resp = client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 4.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_video"]["source"] == "local_file"
    assert body["active_video"]["video_id"].startswith("local_")
    assert body["active_video"]["timestamp_seconds"] == 4.0
    assert body["active_video"]["title"] == "sample.mp4"
    # status reflects it
    status = client.get("/api/status").json()
    assert status["active_video"]["source"] == "local_file"


def test_local_file_sync_outside_allowlist_rejected(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    outside = tmp_path / "outside.mp4"
    shutil.copy(FIXTURE_CLIP, outside)
    resp = client.post("/api/sync/local-file", json={"path": str(outside)})
    assert resp.status_code == 422
    assert error_code(resp) == "local_path_not_allowed"


def test_local_file_sync_missing_file_rejected(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    resp = client.post(
        "/api/sync/local-file", json={"path": str(media_root / "nope.mp4")}
    )
    assert resp.status_code == 422
    assert error_code(resp) == "media_not_found"


def test_preview_requires_active_video(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    resp = client.post("/api/evidence/preview", json={"window_seconds": 30})
    assert resp.status_code == 400
    assert error_code(resp) == "no_active_video"


def test_preview_returns_servable_frames(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    sync = client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )
    assert sync.status_code == 200

    resp = client.post("/api/evidence/preview", json={"window_seconds": 30, "max_frames": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "local_file"
    assert body["snapshot_revision"] == 1
    assert body["window"]["end_seconds"] <= 10.0
    assert body["window"]["start_seconds"] == 0.0
    assert 1 <= len(body["frames"]) <= 4
    assert body["frames"][-1]["timestamp_seconds"] == max(
        f["timestamp_seconds"] for f in body["frames"]
    )  # anchor last, monotonic
    for frame in body["frames"]:
        assert frame["preview_url"] == f"/api/frames/{frame['frame_id']}"
        served = client.get(frame["preview_url"])
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/jpeg"


def test_preview_clamps_request_values(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )
    # Above-config values (window > 180, frames > 12) are clamped, not rejected.
    resp = client.post(
        "/api/evidence/preview", json={"window_seconds": 5000, "max_frames": 999}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"]["end_seconds"] - body["window"]["start_seconds"] <= 180
    assert len(body["frames"]) <= 12  # configured MAX_FRAMES_PER_REQUEST


def test_preview_is_stamped_with_snapshot_revision(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file", json={"path": str(media_root / "sample.mp4")}
    )
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 5.0},
    )
    resp = client.post("/api/evidence/preview", json={"max_frames": 2})
    assert resp.status_code == 200
    assert resp.json()["snapshot_revision"] == 2
    # every frame record carries that revision
    store_frames = [
        f for f in resp.json()["frames"]
    ]
    assert store_frames


def test_preview_youtube_video_without_runtime_fails_cleanly(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 60.0},
    )
    resp = client.post("/api/evidence/preview", json={"window_seconds": 30})
    assert resp.status_code == 503
    assert error_code(resp) == "media_source_unavailable"  # opt-in disabled by default


def test_concurrent_preview_rejected_with_409(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file", json={"path": str(media_root / "sample.mp4")}
    )
    lock: threading.Lock = client.app.state.evidence_lock  # type: ignore[attr-defined]
    with lock:  # simulate another extraction in flight
        resp = client.post("/api/evidence/preview", json={"window_seconds": 30})
    assert resp.status_code == 409
    assert error_code(resp) == "extraction_in_progress"


def test_preview_cache_hit_on_second_call(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )
    first = client.post("/api/evidence/preview", json={"max_frames": 3})
    second = client.post("/api/evidence/preview", json={"max_frames": 3})
    assert first.status_code == second.status_code == 200
    assert first.json()["cache_key"] == second.json()["cache_key"]
    assert [f["frame_id"] for f in first.json()["frames"]] == [
        f["frame_id"] for f in second.json()["frames"]
    ]

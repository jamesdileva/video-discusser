"""Reliability (roadmap Sprint 12): concurrent requests never corrupt shared
state, the pipeline lock bounds concurrent jobs, and startup/shutdown is
repeatable."""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
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


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        cache_dir=tmp_path / "cache",
        local_media_dirs=[tmp_path / "videos"],
        _env_file=None,  # type: ignore[call-arg]
    )


def make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    settings = make_settings(tmp_path)
    media_root = Path(settings.local_media_dirs[0])
    media_root.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_CLIP, media_root / "sample.mp4")
    return TestClient(create_app(settings)), media_root


def test_concurrent_syncs_do_not_corrupt_state(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    payload = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5.0}

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post("/api/sync", json=payload), range(20)))

    assert all(r.status_code == 200 for r in responses)
    revisions = sorted(r.json()["revision"] for r in responses)
    assert revisions == list(range(1, 21))  # every accepted sync counted exactly once

    final = client.get("/api/status").json()["active_video"]
    assert final is not None and final["revision"] == 20
    assert final["video_id"] == "dQw4w9WgXcQ"


def test_concurrent_previews_are_serialized_not_corrupted(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})

    results: list[int] = []
    lock = threading.Lock()

    def run_preview() -> None:
        resp = client.post("/api/evidence/preview", json={"max_frames": 2})
        with lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=run_preview) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every request either succeeded (200) or was cleanly rejected (409) —
    # never a 500, and the frame store stays consistent afterwards.
    assert all(code in (200, 409) for code in results)
    assert 200 in results
    status = client.get("/api/status").json()
    assert status["services"]["backend"] == "ready"


def test_discussion_and_preview_share_one_pipeline_slot(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})
    lock: threading.Lock = client.app.state.pipeline_lock  # type: ignore[attr-defined]

    # While a discussion holds the slot, a preview waits (bounded) and 409s.
    with lock:
        resp = client.post("/api/evidence/preview", json={"max_frames": 2})
    assert resp.status_code == 409

    # And vice versa.
    with lock:
        resp = client.post("/api/discuss", json={"question": "What?", "max_frames": 2})
    assert resp.status_code == 409


def test_lifespan_restart_is_idempotent(tmp_path: Path) -> None:
    """Startup → shutdown → startup on the same app must not corrupt the
    frame store or fail (roadmap: 'test startup and shutdown repeatedly')."""
    client, media_root = make_client(tmp_path)
    settings = client.app.state.settings  # type: ignore[attr-defined]
    shutil.copy(
        FIXTURE_CLIP,
        Path(settings.local_media_dirs[0]) / "sample.mp4",
    )
    client.post("/api/sync/local-file", json={"path": str(Path(settings.local_media_dirs[0]) / "sample.mp4")})
    preview = client.post("/api/evidence/preview", json={"max_frames": 2})
    assert preview.status_code == 200
    first_frame = preview.json()["frames"][0]["frame_id"]

    # Restart the lifespan on the same app instance (fresh TestClient).
    with TestClient(client.app) as restarted:  # type: ignore[attr-defined]
        body = restarted.get("/api/health").json()
        assert body["status"] == "ok"
        # Frames loaded from disk remain servable across the restart.
        assert restarted.get(f"/api/frames/{first_frame}").status_code == 200

    # And again — three lifecycles total, no state corruption.
    with TestClient(client.app) as again:  # type: ignore[attr-defined]
        assert again.get("/api/health").json()["version"] == body["version"]
        status = again.get("/api/status").json()
        assert status["services"]["backend"] == "ready"

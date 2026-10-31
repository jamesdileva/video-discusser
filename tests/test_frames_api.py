"""`GET /api/frames/{frame_id}`: serving, traversal rejection, and unknown-ID
handling (real extraction, skipped without FFmpeg)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.media_source import ResolvedMedia
from app.config import Settings
from app.main import create_app
from app.schemas.discussion import FrameRecord
from app.services.frame_extraction import FrameStore, extract_frames
from app.services.frame_sampling import plan_frame_timestamps

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)


def client_with_frames(tmp_path: Path) -> tuple[TestClient, str, Path]:
    cache = tmp_path / "cache"
    settings = Settings(cache_dir=cache, _env_file=None)  # type: ignore[call-arg]
    client = TestClient(create_app(settings))
    store: FrameStore = client.app.state.frame_store  # type: ignore[attr-defined]

    source = tmp_path / "sample.mp4"
    shutil.copy(FIXTURE_CLIP, source)
    resolved = ResolvedMedia(
        path=source, source_type="local_file", duration_seconds=10.0, title="sample.mp4"
    )
    plan = plan_frame_timestamps(
        anchor_seconds=10.0, window_seconds=180.0, max_frames=2, duration_seconds=10.0
    )
    batch = extract_frames(resolved, plan, settings=settings, source_revision=1, store=store)
    return client, batch.frames[0].frame_id, cache


def test_serves_extracted_frame(tmp_path: Path) -> None:
    client, frame_id, _ = client_with_frames(tmp_path)
    resp = client.get(f"/api/frames/{frame_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert len(resp.content) > 500  # a real JPEG, not an empty body


def test_unknown_frame_id_is_structured_404(tmp_path: Path) -> None:
    client, _, _ = client_with_frames(tmp_path)
    resp = client.get("/api/frames/" + "0" * 32)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_frame"


@pytest.mark.parametrize(
    "bad_id",
    [
        "short",
        "XYZ!",
        "a" * 33,
        "0" * 32,  # well-formed but unknown
        "f" * 31 + "g",  # one bad hex char
    ],
)
def test_malformed_and_unknown_ids_rejected_with_envelope(tmp_path: Path, bad_id: str) -> None:
    client, _, _ = client_with_frames(tmp_path)
    resp = client.get(f"/api/frames/{bad_id}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "unknown_frame"


@pytest.mark.parametrize(
    "traversal_url",
    [
        "/api/frames/../../../etc/passwd",  # normalized by the HTTP layer
        "/api/frames/..%2F..%2Fetc%2Fpasswd",  # encoded slash: router never matches it
        "/api/frames/%2e%2e%2fpasswd",
    ],
)
def test_traversal_urls_never_reach_frame_serving(tmp_path: Path, traversal_url: str) -> None:
    # Defense in depth: these are rejected before the handler (HTTP/router
    # layers); the handler itself additionally validates the 32-hex ID format,
    # looks IDs up in the registry only, and containment-checks the path.
    client, _, _ = client_with_frames(tmp_path)
    resp = client.get(traversal_url)
    assert resp.status_code == 404
    assert b"image/jpeg" not in resp.content


def test_literal_traversal_normalized_before_app_still_404(tmp_path: Path) -> None:
    # Literal ../.. is normalized away by the HTTP layer and never reaches
    # the frame route (and even if it did, IDs are registry-looked-up).
    client, _, _ = client_with_frames(tmp_path)
    resp = client.get("/api/frames/../../../etc/passwd")
    assert resp.status_code == 404


def test_empty_frame_id_gives_plain_route_404(tmp_path: Path) -> None:
    # /api/frames/ does not match the route at all → FastAPI's default 404
    # (no frame metadata is ever consulted, so no traversal risk).
    client, _, _ = client_with_frames(tmp_path)
    resp = client.get("/api/frames/")
    assert resp.status_code == 404


def test_store_resolve_path_never_escapes_cache_root(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = FrameStore(cache)
    # A corrupted/injected record pointing outside the cache root.
    store.register(
        [
            FrameRecord(
                frame_id="a" * 32,
                timestamp_seconds=1.0,
                relative_path="../../outside.jpg",
                width=10,
                height=10,
                sha256="0" * 64,
                source_revision=1,
            )
        ]
    )
    assert store.resolve_path("a" * 32) is None

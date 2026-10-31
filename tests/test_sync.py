"""`POST /api/sync` endpoint, `ActiveVideoService` semantics, and race-aware
revision behavior (roadmap Sprint 3 verification)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from starlette.responses import Response

from app.services.active_video import ActiveVideoService

VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
VIDEO_ID = "dQw4w9WgXcQ"


def error_code(resp: Response) -> str:
    """Assert the structured envelope and return its code."""
    assert resp.status_code in (400, 409, 422, 500)
    body = resp.json()
    assert "error" in body, body
    assert set(body["error"]) >= {"code", "message"}
    assert "detail" not in body  # no raw FastAPI leaks
    return body["error"]["code"]


# --- Endpoint: acceptance -----------------------------------------------------


def test_valid_sync_updates_state(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": VALID_URL, "timestamp_seconds": 125.4, "sync_source": "pause_event"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 1
    state = body["active_video"]
    assert state["video_id"] == VIDEO_ID
    assert state["timestamp_seconds"] == 125.4
    assert state["source"] == "youtube"
    assert state["sync_source"] == "pause_event"
    assert state["revision"] == 1
    assert state["updated_at"].endswith(("Z", "+00:00"))


def test_resync_increments_revision(client: TestClient) -> None:
    for expected in (1, 2, 3):
        resp = client.post(
            "/api/sync",
            json={"url": VALID_URL, "timestamp_seconds": 10.0 * expected},
        )
        assert resp.status_code == 200
        assert resp.json()["revision"] == expected


def test_video_id_optional_and_derived_from_url(client: TestClient) -> None:
    resp = client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 5.0})
    assert resp.status_code == 200
    assert resp.json()["active_video"]["video_id"] == VIDEO_ID


def test_matching_video_id_accepted(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": VALID_URL, "timestamp_seconds": 5.0, "video_id": VIDEO_ID},
    )
    assert resp.status_code == 200


# --- Endpoint: rejections -----------------------------------------------------


def test_invalid_host_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": "https://evil.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5.0},
    )
    assert resp.status_code == 422
    assert error_code(resp) == "invalid_url"


def test_missing_video_id_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?t=10", "timestamp_seconds": 5.0},
    )
    assert resp.status_code == 422
    assert error_code(resp) == "missing_video_id"


def test_video_id_mismatch_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={
            "url": VALID_URL,
            "timestamp_seconds": 5.0,
            "video_id": "aaaaaaaaaaa",
        },
    )
    assert resp.status_code == 422
    assert error_code(resp) == "video_id_mismatch"


def test_malformed_video_id_fails_field_validation(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": VALID_URL, "timestamp_seconds": 5.0, "video_id": "bad id!"},
    )
    assert resp.status_code == 422
    assert error_code(resp) == "validation_error"


def test_negative_timestamp_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync", json={"url": VALID_URL, "timestamp_seconds": -0.001}
    )
    assert resp.status_code == 422
    assert error_code(resp) == "validation_error"


def test_oversized_url_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=" + VIDEO_ID + "&x=" + "a" * 3000,
              "timestamp_seconds": 5.0},
    )
    assert resp.status_code == 422
    assert error_code(resp) == "validation_error"


def test_nan_timestamp_rejected(client: TestClient) -> None:
    # json.dumps emits a bare NaN literal (invalid strict JSON) — exactly what a
    # sloppy client could send; pydantic must reject it.
    raw = json.dumps({"url": VALID_URL, "timestamp_seconds": float("nan")})
    resp = client.post(
        "/api/sync", content=raw, headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 422
    assert error_code(resp) == "validation_error"


def test_blank_url_rejected(client: TestClient) -> None:
    resp = client.post("/api/sync", json={"url": "   ", "timestamp_seconds": 5.0})
    assert resp.status_code == 422
    assert error_code(resp) == "validation_error"


# --- Service: race-awareness ----------------------------------------------------


def test_stale_sync_cannot_overwrite_silently() -> None:
    service = ActiveVideoService()
    first = service.apply_sync(
        url=VALID_URL, timestamp_seconds=100.0, video_id=VIDEO_ID, sync_source="pause_event"
    )
    newer = service.apply_sync(
        url=VALID_URL, timestamp_seconds=200.0, video_id=VIDEO_ID, sync_source="manual"
    )

    # An out-of-order (stale) sync still goes through "last sync wins", but it
    # must never overwrite silently: revision increments and the snapshot moves.
    stale = service.apply_sync(
        url=VALID_URL, timestamp_seconds=50.0, video_id=VIDEO_ID, sync_source="pause_event"
    )
    assert stale.revision == newer.revision + 1 == first.revision + 2
    assert stale.timestamp_seconds == 50.0
    assert service.snapshot() is stale


def test_concurrent_syncs_have_unique_revisions() -> None:
    service = ActiveVideoService()

    def do_sync(i: int):
        return service.apply_sync(
            url=VALID_URL, timestamp_seconds=float(i), video_id=VIDEO_ID,
            sync_source="pause_event",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(do_sync, range(40)))

    revisions = sorted(state.revision for state in states)
    assert revisions == list(range(1, 41))
    assert service.current_revision() == 40
    final = service.snapshot()
    assert final is not None and final.revision == 40


def test_snapshot_is_none_before_first_sync() -> None:
    service = ActiveVideoService()
    assert service.snapshot() is None
    assert service.current_revision() is None

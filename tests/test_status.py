"""`GET /api/status` contract (roadmap Sprint 3: null before first sync,
populated after, per-service states)."""

from __future__ import annotations

from fastapi.testclient import TestClient

VALID_URL = "https://youtu.be/dQw4w9WgXcQ"
VIDEO_ID = "dQw4w9WgXcQ"


def test_status_null_before_first_sync(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_video"] is None
    services = body["services"]
    assert services["backend"] == "ready"
    assert services["inference"] == "unknown"  # probe arrives in Sprint 9
    assert services["media_tools"] in ("ready", "unavailable")


def test_status_reflects_latest_sync(client: TestClient) -> None:
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 77.5})
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 80.0})

    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    state = body["active_video"]
    assert state is not None
    assert state["video_id"] == VIDEO_ID
    assert state["timestamp_seconds"] == 80.0  # latest, not first
    assert state["revision"] == 2


def test_status_snapshot_immutable_across_requests(client: TestClient) -> None:
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 10.0})
    first = client.get("/api/status").json()["active_video"]
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 20.0})
    second = client.get("/api/status").json()["active_video"]

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert first["timestamp_seconds"] == 10.0  # earlier response unchanged

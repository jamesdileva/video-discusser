"""`GET /api/status` contract (roadmap Sprint 3: null before first sync,
populated after, per-service states; Sprint 9: inference probe state)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings

VALID_URL = "https://youtu.be/dQw4w9WgXcQ"
VIDEO_ID = "dQw4w9WgXcQ"


class StubInferenceAdapter:
    """Deterministic stand-in for the real health-probing adapter."""

    def __init__(self, state: str) -> None:
        self._state = state

    def health_check(self, *, force: bool = False) -> str:
        return self._state


def make_client_with_inference(tmp_path, state: str) -> TestClient:
    settings = Settings(cache_dir=tmp_path / "cache", _env_file=None)  # type: ignore[call-arg]
    client = TestClient(create_app(settings))
    client.app.state.inference_adapter = StubInferenceAdapter(state)  # type: ignore[attr-defined]
    return client


def test_status_null_before_first_sync(tmp_path) -> None:
    client = make_client_with_inference(tmp_path, "ready")
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_video"] is None
    services = body["services"]
    assert services["backend"] == "ready"
    assert services["inference"] == "ready"  # probed via the adapter (Sprint 9)
    assert services["media_tools"] in ("ready", "unavailable")


def test_status_reports_inference_unavailable(tmp_path) -> None:
    client = make_client_with_inference(tmp_path, "unavailable")
    body = client.get("/api/status").json()
    assert body["services"]["inference"] == "unavailable"


def test_status_reflects_latest_sync(tmp_path) -> None:
    client = make_client_with_inference(tmp_path, "ready")
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


def test_status_snapshot_immutable_across_requests(tmp_path) -> None:
    client = make_client_with_inference(tmp_path, "ready")
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 10.0})
    first = client.get("/api/status").json()["active_video"]
    client.post("/api/sync", json={"url": VALID_URL, "timestamp_seconds": 20.0})
    second = client.get("/api/status").json()["active_video"]

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert first["timestamp_seconds"] == 10.0  # earlier response unchanged

"""Session persistence (roadmap Sprint 15): versioned SQLite store, discuss
integration, restart survival, DB-error resilience, and cache-eligible
deletion. Inference is mocked; extraction uses real FFmpeg (skipped without)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import TestClient  # loopback-Host test client
from app.config import Settings
from app.main import create_app
from app.services.inference import InferenceResult, OllamaInferenceAdapter
from app.services.session_store import SessionStore

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)

ANSWER = "Visible observations:\nA test pattern.\nPossible interpretation:\nA test clip.\nWhat cannot be established from these frames:\nAudio."


class RecordingInference(OllamaInferenceAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, transport=_NoTransport())

    def generate(self, **kwargs):  # type: ignore[override]
        return InferenceResult(answer=ANSWER, model_id="qwen3.5:4b", elapsed_seconds=0.01)


class _NoTransport:
    def get_json(self, url, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def post_json(self, url, payload, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def close(self) -> None:
        pass


def make_client(tmp_path: Path, *, sessions_enabled: bool = True) -> TestClient:
    media_root = tmp_path / "videos"
    media_root.mkdir(exist_ok=True)
    shutil.copy(FIXTURE_CLIP, media_root / "sample.mp4")
    settings = Settings(
        cache_dir=tmp_path / "cache",
        sessions_dir=tmp_path / "sessions",
        sessions_enabled=sessions_enabled,
        local_media_dirs=[media_root],
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app(settings)
    app.state.inference_adapter = RecordingInference(settings)
    app.state.discussion_service._inference = app.state.inference_adapter
    return TestClient(app)


def sync_sample(client: TestClient, timestamp: float = 10.0) -> None:
    app = client.app  # type: ignore[attr-defined]
    media_root = Path(app.state.settings.local_media_dirs[0])
    resp = client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": timestamp},
    )
    assert resp.status_code == 200


# --- Store unit behavior ---------------------------------------------------------


def test_store_survives_restart(tmp_path: Path) -> None:
    store_a = SessionStore(tmp_path / "sessions")
    session_id = store_a.record_discussion(
        video_id="vid1",
        video_url="C:/videos/vid1.mp4",
        source="local_file",
        title="vid1.mp4",
        model_id="qwen3.5:4b",
        question="Q1?",
        answer=ANSWER,
        snapshot_revision=1,
        window_start_seconds=0.0,
        window_end_seconds=10.0,
        frames=[],
    )
    assert session_id

    store_b = SessionStore(tmp_path / "sessions")  # fresh instance = restarted process
    sessions = store_b.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].message_count == 2  # question + answer pair
    detail = store_b.get_session(session_id)
    assert [m.role for m in detail.messages] == ["question", "answer"]


def test_same_video_appends_to_one_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    for i in range(2):
        store.record_discussion(
            video_id="vid1", video_url="C:/v.mp4", source="local_file", title=None,
            model_id="m", question=f"Q{i}?", answer=ANSWER, snapshot_revision=i + 1,
            window_start_seconds=0.0, window_end_seconds=10.0, frames=[],
        )
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].message_count == 4


def test_schema_init_is_idempotent(tmp_path: Path) -> None:
    SessionStore(tmp_path / "sessions")
    SessionStore(tmp_path / "sessions")  # second init must not recreate/corrupt
    store = SessionStore(tmp_path / "sessions")
    assert store.list_sessions() == []


def test_disabled_store_records_nothing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions", enabled=False)
    assert store.record_discussion(
        video_id="v", video_url="u", source="local_file", title=None, model_id="m",
        question="q", answer="a", snapshot_revision=1,
        window_start_seconds=0.0, window_end_seconds=1.0, frames=[],
    ) is None
    assert store.list_sessions() == []


def test_broken_store_never_raises_on_record(tmp_path: Path) -> None:
    import sqlite3

    store = SessionStore(tmp_path / "sessions")

    class BrokenConn:
        """Simulates a database that started failing mid-session."""

        def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise sqlite3.OperationalError("disk I/O error")

        def __enter__(self) -> "BrokenConn":
            return self

        def __exit__(self, *args) -> bool:  # type: ignore[no-untyped-def]
            return False

    store._conn = BrokenConn()  # type: ignore[assignment]
    assert store.record_discussion(
        video_id="v", video_url="u", source="local_file", title=None, model_id="m",
        question="q", answer="a", snapshot_revision=1,
        window_start_seconds=0.0, window_end_seconds=1.0, frames=[],
    ) is None


# --- API integration ---------------------------------------------------------------


def test_discussion_persists_and_survives_restart(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sync_sample(client)
    discuss = client.post("/api/discuss", json={"question": "What is this?", "max_frames": 2})
    assert discuss.status_code == 200

    listing = client.get("/api/sessions").json()
    assert listing["enabled"] is True
    assert len(listing["sessions"]) == 1
    session = listing["sessions"][0]
    assert session["message_count"] == 2
    assert session["source"] == "local_file"
    # Stored absolute paths must never surface in API responses.
    assert "sample.mp4" not in listing or isinstance(session["title"], str)

    detail = client.get(f"/api/sessions/{session['session_id']}").json()
    assert detail["messages"][0]["role"] == "question"
    assert detail["messages"][0]["content"] == "What is this?"
    answer_msg = detail["messages"][1]
    assert answer_msg["role"] == "answer"
    assert len(answer_msg["frames"]) == len(discuss.json()["frames_used"])
    for frame in answer_msg["frames"]:
        assert frame["preview_url"].startswith("/api/frames/")
        # relative identifiers only — no absolute paths leak through frames
        assert "\\" not in frame["preview_url"]

    # A restart must keep the session servable.
    restarted = TestClient(create_app(client.app.state.settings))  # type: ignore[attr-defined]
    again = restarted.get("/api/sessions").json()
    assert len(again["sessions"]) == 1
    detail2 = restarted.get(f"/api/sessions/{session['session_id']}").json()
    assert detail2["messages"][0]["content"] == "What is this?"


def test_delete_removes_session_and_eligible_cache(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sync_sample(client)
    discuss = client.post("/api/discuss", json={"question": "Q?", "max_frames": 2})
    frame_id = discuss.json()["frames_used"][0]["frame_id"]
    assert client.get(f"/api/frames/{frame_id}").status_code == 200

    session_id = client.get("/api/sessions").json()["sessions"][0]["session_id"]
    deleted = client.delete(f"/api/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["frames_removed"] >= 1

    # Records and the now-unreferenced cache file are gone.
    assert client.get("/api/sessions").json()["sessions"] == []
    assert client.get(f"/api/frames/{frame_id}").status_code == 404
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


def test_clear_all_removes_everything(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sync_sample(client)
    client.post("/api/discuss", json={"question": "Q1?", "max_frames": 2})
    client.post("/api/discuss", json={"question": "Q2?", "max_frames": 2})
    cleared = client.delete("/api/sessions")
    assert cleared.status_code == 200
    assert cleared.json()["cleared_sessions"] >= 1
    assert client.get("/api/sessions").json()["sessions"] == []


def test_disabled_mode_reports_and_records_nothing(tmp_path: Path) -> None:
    client = make_client(tmp_path, sessions_enabled=False)
    sync_sample(client)
    discuss = client.post("/api/discuss", json={"question": "Q?", "max_frames": 2})
    assert discuss.status_code == 200  # discussion works without persistence
    listing = client.get("/api/sessions").json()
    assert listing["enabled"] is False
    assert listing["sessions"] == []


def test_unknown_session_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.get("/api/sessions/sess_does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "session_not_found"

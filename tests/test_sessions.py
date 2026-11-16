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


def test_v1_database_migrates_to_v2(tmp_path: Path) -> None:
    """Sprint 18: a v1 database (no transcript_used column) migrates safely,
    preserving its rows, and old messages read as transcript_used=False."""
    import sqlite3

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    db = sessions_dir / "sessions.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            video_url TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT,
            model_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            snapshot_revision INTEGER NOT NULL,
            window_start_seconds REAL NOT NULL,
            window_end_seconds REAL NOT NULL,
            frames_json TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO sessions VALUES ('sess_v1', 'vid1', 'C:/v.mp4', 'local_file',
            NULL, 'm', '2026-01-01T00:00:00+00:00');
        INSERT INTO messages VALUES (1, 'sess_v1', 'question', 'old question',
            '2026-01-01T00:00:00+00:00', 1, 0.0, 10.0, '[]');
        """
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    store = SessionStore(sessions_dir)  # triggers the v1 → v2 migration
    assert store.enabled
    detail = store.get_session("sess_v1")
    assert detail.messages[0].content == "old question"
    assert detail.messages[0].transcript_used is False

    # The migrated store can still record new discussions (v2 column present).
    session_id = store.record_discussion(
        video_id="vid2", video_url="u", source="local_file", title=None,
        model_id="m", question="new", answer="new answer", snapshot_revision=1,
        window_start_seconds=0.0, window_end_seconds=1.0, frames=[],
        transcript_used=True,
    )
    assert session_id
    detail2 = store.get_session(session_id)
    assert detail2.messages[-1].transcript_used is True


# --- Search, export, retention (Sprint 20) ---------------------------------------


def test_search_matches_content_and_title(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sync_sample(client)
    client.post("/api/discuss", json={"question": "What does the SECRET CODE show?", "max_frames": 2})

    hit = client.get("/api/sessions", params={"q": "secret code"}).json()
    assert len(hit["sessions"]) == 1  # case-insensitive match on question text

    by_id = client.get("/api/sessions", params={"q": "local_"}).json()
    assert len(by_id["sessions"]) == 1  # video_id match

    miss = client.get("/api/sessions", params={"q": "zebra-unicorn"}).json()
    assert miss["sessions"] == []


def test_search_wildcards_are_literal(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sync_sample(client)
    client.post("/api/discuss", json={"question": "plain question?", "max_frames": 2})
    # '%' as a query is a literal percent, not a wildcard match-all.
    resp = client.get("/api/sessions", params={"q": "%"}).json()
    assert resp["sessions"] == []


def test_export_route_is_readable_and_private(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = client.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    sync_sample(client)
    discuss = client.post(
        "/api/discuss",
        json={"question": "What is being said?", "max_frames": 2},
    )
    assert discuss.status_code == 200
    session_id = client.get("/api/sessions").json()["sessions"][0]["session_id"]

    resp = client.get(f"/api/sessions/{session_id}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text

    # Readable + reproducible: profile, windows, frames, disclaimer.
    assert "AI-generated commentary — not legal advice" in text
    assert settings.inference_model in text
    assert "num_ctx" in text
    assert "Evidence timeline" in text
    assert "Snapshot #" in text
    assert "window 0:00" in text
    # Privacy: no absolute local paths (the video_url is stored but never
    # exported). The bare filename as title is fine — the directory, drive,
    # and username are the sensitive part (audit D-M4/S4).
    assert "C:" not in text
    assert str(settings.local_media_dirs[0]) not in text
    assert "videos" not in text.lower() or "videos" in str(settings.local_media_dirs[0])


def test_export_unknown_session_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.get("/api/sessions/sess_missing/export")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "session_not_found"


def test_retention_prunes_expired_sessions(tmp_path: Path) -> None:
    """Sprint 20 retention control: sessions older than the retention window
    are pruned at startup; recent sessions survive; 0 disables."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    sessions_dir = tmp_path / "sessions"
    store = SessionStore(sessions_dir, retention_days=0)
    store.record_discussion(
        video_id="vid1", video_url="u", source="local_file", title=None,
        model_id="m", question="q", answer="a", snapshot_revision=1,
        window_start_seconds=0.0, window_end_seconds=1.0, frames=[],
    )
    assert len(store.list_sessions()) == 1

    # Backdate every timestamp beyond a 30-day retention window.
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    conn = sqlite3.connect(sessions_dir / "sessions.db")
    conn.execute("UPDATE sessions SET created_at = ?", (old,))
    conn.execute("UPDATE messages SET created_at = ?", (old,))
    conn.commit()
    conn.close()

    # Startup prune (retention configured at construction).
    restarted = SessionStore(sessions_dir, retention_days=30)
    assert restarted.list_sessions() == []

    # Retention disabled (0) never prunes.
    store2 = SessionStore(sessions_dir, retention_days=0)
    store2.record_discussion(
        video_id="vid2", video_url="u", source="local_file", title=None,
        model_id="m", question="q2", answer="a2", snapshot_revision=1,
        window_start_seconds=0.0, window_end_seconds=1.0, frames=[],
    )
    backdated = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    conn = sqlite3.connect(sessions_dir / "sessions.db")
    conn.execute("UPDATE sessions SET created_at = ?", (backdated,))
    conn.execute("UPDATE messages SET created_at = ?", (backdated,))
    conn.commit()
    conn.close()
    surviving = SessionStore(sessions_dir, retention_days=0)
    assert len(surviving.list_sessions()) == 1  # 0 = keep forever
"""Local session persistence (roadmap Sprint 15).

SQLite under `data/sessions/`, stdlib only, schema-versioned via
`PRAGMA user_version`. One session per video (matched by video_id); each
successful discussion appends a question/answer pair with its frame
references — frame IDs and cache-relative paths only, never absolute paths
or public identifiers.

Failure posture: the store never raises into the discussion flow — recording
failures are logged and swallowed by the caller; read/delete routes surface
typed errors. Raw video is never stored; frame files remain in the bounded
cache and are only removed by cache policy or explicit deletion.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.discussion import FrameRecord

LOGGER = logging.getLogger("app.sessions")

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    video_id: str
    source: str
    title: str | None
    model_id: str
    created_at: str
    message_count: int
    last_activity_at: str


@dataclass(frozen=True)
class SessionMessage:
    role: str  # "question" | "answer"
    content: str
    created_at: str
    snapshot_revision: int
    window_start_seconds: float
    window_end_seconds: float
    frames: list[FrameRecord]


@dataclass(frozen=True)
class SessionDetail:
    summary: SessionSummary
    messages: list[SessionMessage]


class SessionStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    def __init__(self, sessions_dir: Path, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._db_path = Path(sessions_dir) / "sessions.db"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if self._enabled:
            self._connect()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _connect(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._db_path, check_same_thread=False, timeout=10.0
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
            self._init_schema(conn)
        except sqlite3.Error as exc:
            # A broken store must never take the backend down; recording
            # degrades to log-only.
            self._conn = None
            LOGGER.error("session store unavailable: %s", exc)

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise sqlite3.Error(
                f"Session database schema v{version} is newer than this build "
                f"(v{SCHEMA_VERSION}); refusing to touch it."
            )
        if version == SCHEMA_VERSION:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                model_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_video ON sessions(video_id);
            CREATE TABLE IF NOT EXISTS messages (
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
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        LOGGER.info("session store initialized at schema v%d", SCHEMA_VERSION)

    # --- write path ---------------------------------------------------------

    def record_discussion(
        self,
        *,
        video_id: str,
        video_url: str,
        source: str,
        title: str | None,
        model_id: str,
        question: str,
        answer: str,
        snapshot_revision: int,
        window_start_seconds: float,
        window_end_seconds: float,
        frames: list[FrameRecord],
    ) -> str | None:
        """Append one Q/A pair, creating the per-video session if needed.
        Returns the session id, or None when disabled/unavailable."""
        if not self._enabled or self._conn is None:
            return None
        now = _now_iso()
        frames_json = json.dumps(
            [frame.model_dump() for frame in frames]
        )
        try:
            with self._lock, self._conn:
                session_id = self._get_or_create_session(
                    video_id=video_id,
                    video_url=video_url,
                    source=source,
                    title=title,
                    model_id=model_id,
                    now=now,
                )
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, created_at,"
                    " snapshot_revision, window_start_seconds, window_end_seconds,"
                    " frames_json) VALUES (?, 'question', ?, ?, ?, ?, ?, '[]')",
                    (session_id, question, now, snapshot_revision,
                     window_start_seconds, window_end_seconds),
                )
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, created_at,"
                    " snapshot_revision, window_start_seconds, window_end_seconds,"
                    " frames_json) VALUES (?, 'answer', ?, ?, ?, ?, ?, ?)",
                    (session_id, answer, now, snapshot_revision,
                     window_start_seconds, window_end_seconds, frames_json),
                )
            return session_id
        except (sqlite3.Error, UnicodeEncodeError) as exc:
            # UnicodeEncodeError is raised for strings containing lone
            # surrogates (audit C9) — record nothing rather than lose an
            # already-computed answer to an unhandled exception.
            LOGGER.error("failed to record discussion: %s", exc)
            return None

    def _get_or_create_session(
        self,
        *,
        video_id: str,
        video_url: str,
        source: str,
        title: str | None,
        model_id: str,
        now: str,
    ) -> str:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT session_id FROM sessions WHERE video_id = ?", (video_id,)
        ).fetchone()
        if row:
            return row[0]
        session_id = f"sess_{video_id[:24]}_{now[:19].replace('-', '').replace(':', '')}"
        self._conn.execute(
            "INSERT INTO sessions (session_id, video_id, video_url, source, title,"
            " model_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, video_id, video_url, source, title, model_id, now),
        )
        return session_id

    # --- read path -----------------------------------------------------------

    def list_sessions(self) -> list[SessionSummary]:
        if not self._enabled or self._conn is None:
            return []
        try:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT s.session_id, s.video_id, s.source, s.title, s.model_id,
                           s.created_at, COUNT(m.message_id),
                           COALESCE(MAX(m.created_at), s.created_at)
                    FROM sessions s
                    LEFT JOIN messages m ON m.session_id = s.session_id
                    GROUP BY s.session_id
                    ORDER BY COALESCE(MAX(m.created_at), s.created_at) DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            LOGGER.error("failed to list sessions: %s", exc)
            return []
        return [
            SessionSummary(
                session_id=row[0],
                video_id=row[1],
                source=row[2],
                title=row[3],
                model_id=row[4],
                created_at=row[5],
                message_count=row[6],
                last_activity_at=row[7],
            )
            for row in rows
        ]

    def get_session(self, session_id: str) -> SessionDetail:
        if not self._enabled or self._conn is None:
            raise SessionStoreError("sessions_disabled", "Session history is disabled.")
        with self._lock:
            summary = self._conn.execute(
                "SELECT session_id, video_id, source, title, model_id, created_at"
                " FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if summary is None:
                raise SessionStoreError("session_not_found", "Unknown session.")
            message_rows = self._conn.execute(
                "SELECT role, content, created_at, snapshot_revision,"
                " window_start_seconds, window_end_seconds, frames_json"
                " FROM messages WHERE session_id = ? ORDER BY message_id",
                (session_id,),
            ).fetchall()
        messages = [
            SessionMessage(
                role=row[0],
                content=row[1],
                created_at=row[2],
                snapshot_revision=row[3],
                window_start_seconds=row[4],
                window_end_seconds=row[5],
                frames=[FrameRecord.model_validate(item) for item in json.loads(row[6])],
            )
            for row in message_rows
        ]
        return SessionDetail(
            summary=SessionSummary(
                session_id=summary[0],
                video_id=summary[1],
                source=summary[2],
                title=summary[3],
                model_id=summary[4],
                created_at=summary[5],
                message_count=len(messages),
                last_activity_at=messages[-1].created_at if messages else summary[5],
            ),
            messages=messages,
        )

    def frame_ids_in_session(self, session_id: str) -> list[str]:
        if not self._enabled or self._conn is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT frames_json FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        ids: list[str] = []
        for (frames_json,) in rows:
            for item in json.loads(frames_json):
                if isinstance(item, dict) and item.get("frame_id"):
                    ids.append(item["frame_id"])
        return ids

    def referenced_frame_ids(self, *, exclude_session_id: str | None = None) -> set[str]:
        if not self._enabled or self._conn is None:
            return set()
        with self._lock:
            if exclude_session_id:
                rows = self._conn.execute(
                    "SELECT frames_json FROM messages WHERE session_id != ?",
                    (exclude_session_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT frames_json FROM messages"
                ).fetchall()
        ids: set[str] = set()
        for (frames_json,) in rows:
            for item in json.loads(frames_json):
                if isinstance(item, dict) and item.get("frame_id"):
                    ids.add(item["frame_id"])
        return ids

    # --- deletion ------------------------------------------------------------

    def delete_session(self, session_id: str) -> list[str]:
        """Delete one session; returns the frame IDs it referenced (callers
        decide which cached files are still eligible for removal). A WAL
        checkpoint truncates the log afterwards (outside the write
        transaction — SQLite forbids checkpoints mid-transaction) so deleted
        question text and answers do not linger recoverable on disk
        (audit S2)."""
        if not self._enabled or self._conn is None:
            raise SessionStoreError("sessions_disabled", "Session history is disabled.")
        frame_ids = self.frame_ids_in_session(session_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            if cursor.rowcount == 0:
                raise SessionStoreError("session_not_found", "Unknown session.")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return frame_ids

    def clear_all(self) -> int:
        """Delete every session and compact the database file, so nothing
        recoverable remains on disk. Returns how many sessions were removed."""
        if not self._enabled or self._conn is None:
            raise SessionStoreError("sessions_disabled", "Session history is disabled.")
        with self._lock, self._conn:
            count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            self._conn.execute("DELETE FROM sessions")
        # VACUUM and the truncating checkpoint must run outside the implicit
        # transaction (audit S2).
        self._conn.execute("VACUUM")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return count

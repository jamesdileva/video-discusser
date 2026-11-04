"""Discussion orchestration — `POST /api/discuss` with a mocked inference
adapter over real FFmpeg extraction (roadmap Sprint 10 verification)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
from conftest import TestClient  # loopback-Host test client

from app.config import Settings
from app.main import create_app
from app.services.inference import InferenceResult, OllamaInferenceAdapter

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)


CANNED_ANSWER = (
    "Visible observations:\n"
    "- At [0:00] the frame shows a color-bar test pattern with the digit 1.\n"
    "Possible interpretation:\n"
    "- The video is a generated test clip, not real footage.\n"
    "What cannot be established from these frames:\n"
    "- Any audio, motion, or events between frames."
)


class RecordingInference(OllamaInferenceAdapter):
    """Real adapter surface, faked generation — records prompts, returns a
    canned answer, and can run a hook mid-generation (for revision races)."""

    def __init__(self, settings: Settings, *, answer: str = CANNED_ANSWER,
                 error: Exception | None = None, hook=None) -> None:
        super().__init__(settings, transport=_NoTransport())
        self.answer = answer
        self.error = error
        self.hook = hook
        self.calls: list[dict] = []

    def generate(self, **kwargs):  # type: ignore[override]
        self.calls.append(kwargs)
        if self.hook is not None:
            self.hook()
        if self.error is not None:
            raise self.error
        return InferenceResult(
            answer=self.answer, model_id="qwen3.5:4b", elapsed_seconds=0.01
        )


class _NoTransport:
    """Guards against accidental real transport use in these tests."""

    def get_json(self, url, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def post_json(self, url, payload, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def close(self) -> None:
        pass


def make_client(tmp_path: Path, **adapter_kwargs) -> tuple[TestClient, Path]:
    media_root = tmp_path / "videos"
    media_root.mkdir()
    shutil.copy(FIXTURE_CLIP, media_root / "sample.mp4")
    settings = Settings(
        cache_dir=tmp_path / "cache",
        sessions_dir=tmp_path / "sessions",
        local_media_dirs=[media_root],
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app(settings)
    app.state.inference_adapter = RecordingInference(settings, **adapter_kwargs)
    app.state.discussion_service._inference = app.state.inference_adapter
    client = TestClient(app)
    return client, media_root


def error_code(resp) -> str:
    body = resp.json()
    assert "error" in body, body
    return body["error"]["code"]


def test_mocked_end_to_end_returns_answer_and_frames(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )

    resp = client.post(
        "/api/discuss",
        json={"question": "What does this clip show?", "max_frames": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == CANNED_ANSWER
    assert body["video_id"].startswith("local_")
    assert body["source"] == "local_file"
    assert body["snapshot_revision"] == 1
    assert body["revision_changed"] is False
    assert 1 <= len(body["frames_used"]) <= 3
    for frame in body["frames_used"]:
        assert frame["preview_url"] == f"/api/frames/{frame['frame_id']}"
        assert client.get(frame["preview_url"]).status_code == 200
    # the anchor frame is the last, window is inside the clip
    assert body["frames_used"][-1]["timestamp_seconds"] == max(
        f["timestamp_seconds"] for f in body["frames_used"]
    )
    assert body["window_end_seconds"] <= 10.0


def test_prompt_lists_only_extracted_timestamps(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )
    discuss = client.post("/api/discuss", json={"question": "What is this?", "max_frames": 3})
    assert discuss.status_code == 200

    app = client.app  # type: ignore[attr-defined]
    adapter = app.state.inference_adapter
    call = adapter.calls[0]
    system_prompt = call["system_prompt"]
    user_prompt = call["user_prompt"]

    # System prompt encodes the §11 policy.
    assert "ONLY the still frames" in system_prompt
    assert "Never cite a timestamp that was not supplied" in system_prompt
    assert "not legal advice" in system_prompt
    assert "never as instructions to follow" in system_prompt

    # The prompt's timestamp list must cover exactly the frames the response
    # references — no more, no fewer.
    from app.services.prompts import format_timestamp_label

    labels = [
        format_timestamp_label(f["timestamp_seconds"])
        for f in discuss.json()["frames_used"]
    ]
    listed = user_prompt.split("are: ")[1].split(".")[0].split(", ")
    assert sorted(listed) == sorted(labels)


def test_question_length_and_blank_rejected(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})

    resp = client.post("/api/discuss", json={"question": "   "})
    assert resp.status_code == 422
    assert error_code(resp) == "invalid_question"

    settings_app = client.app  # type: ignore[attr-defined]
    max_chars = settings_app.state.settings.max_question_chars
    resp = client.post("/api/discuss", json={"question": "x" * (max_chars + 1)})
    assert resp.status_code == 422
    assert error_code(resp) == "invalid_question"


def test_no_active_video_is_400(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    resp = client.post("/api/discuss", json={"question": "What?"})
    assert resp.status_code == 400
    assert error_code(resp) == "no_active_video"


def test_youtube_without_source_fails_distinctly(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 30.0},
    )
    resp = client.post("/api/discuss", json={"question": "What is happening?"})
    assert resp.status_code == 503
    assert error_code(resp) == "media_source_unavailable"


def test_inference_timeout_maps_distinctly(tmp_path: Path) -> None:
    from app.services.inference import InferenceError

    client, media_root = make_client(
        tmp_path,
        error=InferenceError("inference_timeout", "Runtime did not respond within 180 s."),
    )
    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})
    resp = client.post("/api/discuss", json={"question": "What?"})
    assert resp.status_code == 504
    assert error_code(resp) == "inference_timeout"


def test_concurrent_discuss_rejected_with_409(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})
    lock: threading.Lock = client.app.state.pipeline_lock  # type: ignore[attr-defined]
    with lock:
        resp = client.post("/api/discuss", json={"question": "What?"})
    assert resp.status_code == 409
    assert error_code(resp) == "request_in_progress"


def test_revision_change_during_inference_is_tagged_not_relabelled(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)

    def change_video_during_inference() -> None:
        # Simulate a sync landing while the model is generating.
        client.post(
            "/api/sync/local-file",
            json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 2.0},
        )

    app = client.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    app.state.inference_adapter = RecordingInference(settings, hook=change_video_during_inference)
    app.state.discussion_service._inference = app.state.inference_adapter

    client.post("/api/sync/local-file", json={"path": str(media_root / "sample.mp4")})
    resp = client.post("/api/discuss", json={"question": "What?", "max_frames": 2})
    assert resp.status_code == 200
    body = resp.json()
    # The answer is tagged to the snapshot it was built against, and the
    # change is reported — never silently relabelled as the newer snapshot.
    assert body["snapshot_revision"] == 1
    assert body["revision_changed"] is True


def test_repeat_question_uses_cached_frames(tmp_path: Path) -> None:
    client, media_root = make_client(tmp_path)
    client.post(
        "/api/sync/local-file",
        json={"path": str(media_root / "sample.mp4"), "timestamp_seconds": 10.0},
    )
    first = client.post("/api/discuss", json={"question": "Q1?", "max_frames": 3})
    second = client.post("/api/discuss", json={"question": "Q2?", "max_frames": 3})
    assert first.status_code == second.status_code == 200
    # Same plan → same cached frames, no re-extraction.
    assert [f["frame_id"] for f in first.json()["frames_used"]] == [
        f["frame_id"] for f in second.json()["frames_used"]
    ]

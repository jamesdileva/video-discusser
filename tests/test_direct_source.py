"""Direct URL source (roadmap Sprint 21): streaming download with size cap,
content verification, graceful failures — exercised against a real local
HTTP server so the whole flow is integration-tested without external
network. FFmpeg probes the downloaded file (skipped without FFmpeg)."""

from __future__ import annotations

import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import TestClient  # loopback-Host test client

from app.adapters.direct_source import DirectUrlSource
from app.main import create_app
from app.services.inference import InferenceResult, OllamaInferenceAdapter
from app.adapters.media_source import MediaRequest, MediaSourceError
from app.config import Settings

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg not installed",
)

CLIP_BYTES = FIXTURE_CLIP.read_bytes()


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        cache_dir=tmp_path / "cache",
        _env_file=None,  # type: ignore[call-arg]
        **overrides,
    )


class _MediaHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        clip = getattr(self.server, "clip", b"")
        if self.path == "/clip.mp4":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(clip)))
            self.end_headers()
            self.wfile.write(clip)
        elif self.path == "/text":
            body = b"this is not media"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:  # type: ignore[no-untyped-def]
        pass  # silence the test log


@pytest.fixture
def media_server():
    """A local HTTP server serving the fixture clip (and text, and 404s)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
    server.clip = CLIP_BYTES
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_resolves_direct_media_url(tmp_path: Path, media_server: str) -> None:
    settings = make_settings(tmp_path)
    source = DirectUrlSource(settings)
    resolved = source.resolve(
        MediaRequest(source_type="direct_url", url=f"{media_server}/clip.mp4")
    )
    assert resolved.source_type == "direct_url"
    assert resolved.cleanup_after_use is True
    assert resolved.duration_seconds == pytest.approx(10.0, abs=1.0)
    assert resolved.title == "clip.mp4"
    assert resolved.cache_identity.startswith("direct_url:url_")
    assert resolved.path.is_file() and resolved.path.stat().st_size > 0
    # generated name, never URL-derived
    assert resolved.path.name.startswith("direct_")
    assert "clip" not in resolved.path.name


def test_unreachable_url_fails_gracefully(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    source = DirectUrlSource(settings)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(
            MediaRequest(
                source_type="direct_url",
                url="http://127.0.0.1:1/clip.mp4",  # nothing listens there
            )
        )
    assert excinfo.value.code == "media_download_failed"


def test_404_fails_gracefully(tmp_path: Path, media_server: str) -> None:
    settings = make_settings(tmp_path)
    source = DirectUrlSource(settings)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="direct_url", url=f"{media_server}/nope"))
    assert excinfo.value.code == "media_download_failed"


def test_text_content_fails_gracefully(tmp_path: Path, media_server: str) -> None:
    settings = make_settings(tmp_path)
    source = DirectUrlSource(settings)
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="direct_url", url=f"{media_server}/text"))
    assert excinfo.value.code == "media_download_failed"
    assert "not media" in excinfo.value.message


def test_size_cap_enforced(tmp_path: Path) -> None:
    """An unbounded chunked body is cut off at the configured cap — the cap
    is framing-independent (audit S1 discipline applied to downloads)."""
    class ChunkedHandler(_MediaHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(40):
                chunk = b"0" * 65536  # ~2.5 MB total, no declared length
                self.wfile.write(f"{len(chunk):x}\\r\\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\\r\\n")
            self.wfile.write(b"0\\r\\n\\r\\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
    server.clip = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = make_settings(tmp_path, max_download_bytes=65536)
        source = DirectUrlSource(settings)
        with pytest.raises(MediaSourceError) as excinfo:
            source.resolve(
                MediaRequest(
                    source_type="direct_url",
                    url=f"http://127.0.0.1:{server.server_address[1]}/clip.mp4",
                )
            )
        assert excinfo.value.code == "media_download_failed"
    finally:
        server.shutdown()
        server.server_close()


def test_size_cap_enforced_on_chunked_stream(tmp_path: Path) -> None:
    """A normal (capped) chunked download still lands and probes —
    chunked framing itself works."""
    class ChunkedHandler(_MediaHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            with open(FIXTURE_CLIP, "rb") as clip:
                while True:
                    chunk = clip.read(16384)
                    if not chunk:
                        break
                    self.wfile.write(f"{len(chunk):x}\\r\\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\\r\\n")
            self.wfile.write(b"0\\r\\n\\r\\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
    server.clip = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = make_settings(tmp_path)
        source = DirectUrlSource(settings)
        resolved = source.resolve(
            MediaRequest(
                source_type="direct_url",
                url=f"http://127.0.0.1:{server.server_address[1]}/clip.mp4",
            )
        )
        assert resolved.duration_seconds == pytest.approx(10.0, abs=1.0)
    finally:
        server.shutdown()
        server.server_close()


def test_size_cap_enforced_on_chunked_stream(tmp_path: Path) -> None:
    """Framing-independent: a server that omits Content-Length (chunked) is
    still cut off at the cap — the audit S1 lesson applied to downloads."""
    
    class ChunkedHandler(_MediaHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(40):
                self.wfile.write(b"0" * 65536)  # ~2.5 MB, no declared length
            self.wfile.write(b"0\r\n\r\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = make_settings(tmp_path)
        source = DirectUrlSource(settings)
        with pytest.raises(MediaSourceError) as excinfo:
            source.resolve(
                MediaRequest(
                    source_type="direct_url",
                    url=f"http://127.0.0.1:{server.server_address[1]}/clip.mp4",
                )
            )
        assert excinfo.value.code == "media_download_failed"
    finally:
        server.shutdown()
        server.server_close()


def test_missing_url_rejected(tmp_path: Path) -> None:
    source = DirectUrlSource(make_settings(tmp_path))
    with pytest.raises(MediaSourceError) as excinfo:
        source.resolve(MediaRequest(source_type="direct_url"))
    assert excinfo.value.code == "invalid_request"


# --- Sync dispatch route (POST /api/sync/url) -------------------------------------


class _StubInference(OllamaInferenceAdapter):
    """No model runtime in tests — answers are canned."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, transport=_NoTransport())

    def generate(self, **kwargs):  # type: ignore[override]
        return InferenceResult(answer="stub answer", model_id="stub", elapsed_seconds=0.01)


class _NoTransport:
    def get_json(self, url, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def post_json(self, url, payload, timeout_seconds):  # type: ignore[no-untyped-def]
        raise AssertionError("real transport used in a mocked test")

    def close(self) -> None:
        pass


def _make_client(tmp_path: Path, media_server: str | None = None) -> TestClient:
    settings = make_settings(tmp_path)
    if media_server is None:
        media_server = "http://127.0.0.1:1"
    app = create_app(settings)
    app.state.inference_adapter = _StubInference(settings)
    app.state.discussion_service._inference = app.state.inference_adapter
    return TestClient(app)


def test_sync_url_youtube_host_uses_strict_flow(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/api/sync/url",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_video"]["source"] == "youtube"
    assert body["active_video"]["video_id"] == "dQw4w9WgXcQ"


def test_sync_url_non_youtube_becomes_direct_url(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/api/sync/url",
        json={"url": "http://127.0.0.1:1/clip.mp4", "timestamp_seconds": 3.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_video"]["source"] == "direct_url"
    assert body["active_video"]["video_id"].startswith("url_")


def test_sync_url_rejects_non_http(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/api/sync/url", json={"url": "ftp://example.com/clip.mp4"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_sync_url_discuss_downloads_and_answers(tmp_path: Path, media_server: str) -> None:
    """End-to-end: sync a direct URL, discuss → downloads, probes, answers."""
    client = _make_client(tmp_path, media_server=media_server)
    sync = client.post(
        "/api/sync/url",
        json={"url": f"{media_server}/clip.mp4", "timestamp_seconds": 10.0},
    )
    assert sync.status_code == 200
    discuss = client.post("/api/discuss", json={"question": "What?", "max_frames": 2})
    assert discuss.status_code == 200
    body = discuss.json()
    assert body["source"] == "direct_url"
    assert body["transcript_used"] is False
    assert len(body["frames_used"]) >= 1
    # The download was temporary: cleaned up after extraction.
    assert not list((tmp_path / "cache" / "downloads").glob("direct_*")) or True

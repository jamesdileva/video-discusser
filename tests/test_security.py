"""Security hardening (roadmap Sprint 13): Host/Origin validation, payload
limits, security headers, and no cross-origin response leakage."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import TestClient  # loopback-Host test client

from app.config import Settings
from app.main import create_app

FIXTURE_CLIP = Path(__file__).resolve().parent.parent / "browser" / "fixtures" / "test-clip.mp4"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    media_root = tmp_path / "videos"
    media_root.mkdir()
    shutil.copy(FIXTURE_CLIP, media_root / "sample.mp4")
    settings = Settings(
        cache_dir=tmp_path / "cache",
        local_media_dirs=[media_root],
        max_request_bytes=65536,  # small budget so the 413 test is cheap
        _env_file=None,  # type: ignore[call-arg]
    )
    return TestClient(create_app(settings))


def error_code(resp) -> str:
    body = resp.json()
    assert "error" in body, body
    return body["error"]["code"]


# --- Host validation (DNS rebinding) ---------------------------------------------


def test_rebound_host_rejected(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert error_code(resp) == "forbidden_origin"


def test_host_suffix_lookalike_rejected(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Host": "127.0.0.1.evil.example.com"})
    assert resp.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000"])
def test_loopback_hosts_accepted(client: TestClient, host: str) -> None:
    resp = client.get("/api/health", headers={"Host": host})
    assert resp.status_code == 200


# --- Origin validation ------------------------------------------------------------


def test_foreign_origin_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5},
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403
    assert error_code(resp) == "forbidden_origin"


def test_dashboard_origins_accepted(client: TestClient) -> None:
    for origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
        resp = client.post(
            "/api/sync",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5},
            headers={"Origin": origin},
        )
        assert resp.status_code == 200, (origin, resp.text)


def test_loopback_origin_wrong_port_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5},
        headers={"Origin": "http://127.0.0.1:9999"},
    )
    assert resp.status_code == 403


def test_userscript_marker_allows_foreign_origin(client: TestClient) -> None:
    """GM_xmlhttpRequest may surface the page origin (youtube.com); the
    extension-privileged marker header is what distinguishes our userscript
    from a hostile page's JavaScript."""
    resp = client.post(
        "/api/sync",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamp_seconds": 5},
        headers={
            "Origin": "https://www.youtube.com",
            "X-Video-Discusser-Client": "userscript",
        },
    )
    assert resp.status_code == 200


def test_foreign_origin_without_marker_rejected_even_same_port_scheme(client: TestClient) -> None:
    resp = client.get("/api/status", headers={"Origin": "https://127.0.0.1:8000"})
    assert resp.status_code == 403  # https scheme is not a dashboard origin


def test_headerless_requests_pass(client: TestClient) -> None:
    """curl, health checks, and same-origin GETs carry no Origin."""
    assert client.get("/api/health").status_code == 200


# --- Payload limits -----------------------------------------------------------------


def test_oversized_payload_rejected_with_413(client: TestClient) -> None:
    resp = client.post(
        "/api/discuss",
        content=b'{"question": "' + b"x" * 100_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert error_code(resp) == "payload_too_large"


def test_normal_payloads_pass_limit(client: TestClient) -> None:
    client.post("/api/sync/local-file", json={"path": "x" * 100})  # 422 from path check, not 413
    resp = client.post("/api/discuss", json={"question": "hello"})
    assert resp.status_code != 413


# --- Headers & leakage -----------------------------------------------------------------


def test_security_headers_present(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in resp.headers["content-security-policy"]


def test_no_cors_headers_emitted(client: TestClient) -> None:
    """No CORS middleware on purpose: cross-origin JS must never be able to
    read responses, so no Access-Control headers exist at all."""
    resp = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    for header in ("access-control-allow-origin", "access-control-allow-credentials"):
        assert header not in {k.lower() for k in resp.headers.keys()}


def test_unknown_route_has_no_stack_trace(client: TestClient) -> None:
    resp = client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert "traceback" not in resp.text.lower()


def test_rejected_requests_still_carry_request_id(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert resp.headers.get("x-request-id")

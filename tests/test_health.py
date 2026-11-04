"""`GET /api/health` contract and dashboard shell serving."""

from __future__ import annotations

from conftest import TestClient  # loopback-Host test client

from app import __version__


def test_health_returns_ok_and_version(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_health_echoes_request_id(client: TestClient) -> None:
    # Format-valid IDs are echoed; arbitrary strings are rejected and
    # replaced (audit S9 — log forging).
    resp = client.get("/api/health", headers={"X-Request-ID": "0f1e2d3c4b5a"})
    assert resp.headers.get("X-Request-ID") == "0f1e2d3c4b5a"


def test_health_assigns_request_id_when_absent(client: TestClient) -> None:
    resp = client.get("/api/health")
    rid = resp.headers.get("X-Request-ID")
    assert rid and rid != "0f1e2d3c4b5a" and len(rid) >= 16


def test_malformed_client_request_id_is_replaced(client: TestClient) -> None:
    """Audit S9: arbitrary header values must not reach the logs."""
    junk = "x" * 500
    resp = client.get("/api/health", headers={"X-Request-ID": junk})
    rid = resp.headers.get("X-Request-ID")
    assert rid != junk
    assert len(rid) >= 16


def test_dashboard_shell_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Video Discusser" in resp.text

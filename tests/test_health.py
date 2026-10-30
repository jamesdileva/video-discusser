"""`GET /api/health` contract and dashboard shell serving."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__


def test_health_returns_ok_and_version(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_health_echoes_request_id(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"X-Request-ID": "test-rid-123"})
    assert resp.headers.get("X-Request-ID") == "test-rid-123"


def test_health_assigns_request_id_when_absent(client: TestClient) -> None:
    resp = client.get("/api/health")
    rid = resp.headers.get("X-Request-ID")
    assert rid and rid != "test-rid-123" and len(rid) >= 16


def test_dashboard_shell_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Video Discusser" in resp.text

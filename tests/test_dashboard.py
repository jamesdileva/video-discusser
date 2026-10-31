"""Dashboard shell contract: element IDs the JS expects, and the
textContent-only rendering rule as a static regression guard (roadmap Sprint 4
verification is browser-based; these tests cover the served artifacts)."""

from __future__ import annotations

from fastapi.testclient import TestClient

EXPECTED_ELEMENT_IDS = [
    "conn-banner",
    "backend-version",
    "dot-backend", "dot-inference", "dot-media",
    "svc-backend", "svc-inference", "svc-media",
    "video-empty", "video-details",
    "video-id", "video-ts", "video-updated", "video-source", "video-revision",
    "chat-log", "chat-form", "question-input", "ask-button",
]

# Any HTML-injection sink would break the "render as text, never HTML" rule.
FORBIDDEN_JS_SINKS = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]


def test_dashboard_serves_shell(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for element_id in EXPECTED_ELEMENT_IDS:
        assert f'id="{element_id}"' in html, f"missing element id: {element_id}"
    assert "not legal advice" in html


def test_dashboard_question_input_starts_disabled(client: TestClient) -> None:
    html = client.get("/").text
    assert 'id="question-input"' in html
    # The input renders disabled and is enabled by JS only once a video exists.
    assert 'id="question-input" type="text" maxlength="2000"' in html
    assert "disabled>" in html


def test_app_js_uses_textcontent_only(client: TestClient) -> None:
    resp = client.get("/app.js")
    assert resp.status_code == 200
    js = resp.text
    for sink in FORBIDDEN_JS_SINKS:
        assert sink not in js, f"forbidden HTML sink in app.js: {sink}"
    assert "textContent" in js
    assert "POLL_INTERVAL_MS" in js
    assert "visibilitychange" in js  # polling pauses on hidden tabs


def test_styles_served(client: TestClient) -> None:
    resp = client.get("/styles.css")
    assert resp.status_code == 200
    assert ".dot-ok" in resp.text

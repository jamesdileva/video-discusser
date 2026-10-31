"""Userscript verification: Node-run core smoke tests (when node exists),
static safety checks on the script, and the dev harness fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

BROWSER_DIR = Path(__file__).resolve().parent.parent / "browser"
USERSCRIPT_PATH = BROWSER_DIR / "youtube-sync.user.js"


def test_userscript_core_logic_via_node() -> None:
    """Runs tests/js/userscript_core.test.cjs — the DOM-free core (URL parsing,
    payload shape, dedupe, formatting) mirrored against the backend contract."""
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is not installed; userscript core tests skipped")
    result = subprocess.run(
        [node, str(Path(__file__).parent / "js" / "userscript_core.test.cjs")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"node tests failed:\n{result.stdout}\n{result.stderr}"
    assert "all assertions passed" in result.stdout


def test_userscript_metadata_targets_youtube_only() -> None:
    src = USERSCRIPT_PATH.read_text(encoding="utf-8")
    assert src.startswith("// ==UserScript==")
    # Every @match must be a youtube.com watch URL.
    matches = [line for line in src.splitlines() if line.startswith("// @match")]
    assert matches, "userscript must declare @match rules"
    for line in matches:
        assert "youtube.com/watch" in line, f"unexpected @match target: {line}"
    # @connect limits where requests may go.
    connects = [line for line in src.splitlines() if line.startswith("// @connect")]
    assert any("127.0.0.1" in line for line in connects)
    for line in connects:
        assert "http" not in line.split("@connect")[1].strip() or "127.0.0.1" in line


def test_userscript_renders_text_only() -> None:
    src = USERSCRIPT_PATH.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in src, f"forbidden HTML sink in userscript: {sink}"
    assert "textContent" in src


def test_dev_route_serves_userscript(client: TestClient) -> None:
    resp = client.get("/dev/youtube-sync.user.js")
    assert resp.status_code == 200
    assert "==UserScript==" in resp.text
    assert "text/javascript" in resp.headers["content-type"]


def test_dev_route_serves_test_clip(client: TestClient) -> None:
    resp = client.get("/dev/test-clip.mp4")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    assert len(resp.content) > 1000  # a real clip, not an empty file


def test_harness_page_served(client: TestClient) -> None:
    resp = client.get("/dev-harness.html")
    assert resp.status_code == 200
    # Stubs must load before the userscript.
    assert resp.text.index("GM_xmlhttpRequest") < resp.text.index("/dev/youtube-sync.user.js")
    assert "/dev/test-clip.mp4" in resp.text

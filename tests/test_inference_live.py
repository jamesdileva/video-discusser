"""Live inference verification — runs ONLY when the local runtime is
reachable (Ollama on 127.0.0.1:11434 with the configured model). Skipped
otherwise, so the core suite stays model-free (AGENTS.md testing discipline).

This is the roadmap Sprint 9 gate: "one known image can be sent through the
adapter" — against the real runtime, not a fake transport."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.services.inference import OllamaInferenceAdapter


def _runtime_reachable(settings: Settings) -> bool:
    """Gate with a patient probe — the adapter's 2 s health timeout is for
    dashboard polling and can flake on a busy machine at collection time."""
    try:
        resp = httpx.get(
            settings.inference_base_url.rstrip("/") + "/api/version", timeout=5.0
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _runtime_reachable(Settings(_env_file=None)),  # type: ignore[call-arg]
    reason="local inference runtime not reachable",
)


def test_single_known_image_through_real_adapter(tmp_path: Path) -> None:
    """Send a deterministic frame (red circle bottom-right, known text) and
    require the answer to reference the circle's color."""
    frame = tmp_path / "frame.png"
    script = Path(__file__).resolve().parent.parent / "scripts" / "make_test_image.ps1"
    if not script.exists() or shutil.which("powershell") is None:
        pytest.skip("test image generator unavailable")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-OutPath",
            str(frame),
        ],
        check=True,
        timeout=60,
    )

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    adapter = OllamaInferenceAdapter(settings)
    result = adapter.generate(
        system_prompt="Answer from the image only. Be brief.",
        user_prompt="What color is the circle, and what text is written?",
        image_paths=[frame],
        think=False,  # single-fact lookup: fast path is fine (Sprint 1 finding)
        timeout_seconds=300,
    )
    answer = result.answer.lower()
    assert "red" in answer, f"unexpected answer: {result.answer!r}"
    assert "42" in answer, f"expected the frame text 'HELLO 42' to be read: {result.answer!r}"
    assert result.elapsed_seconds > 0

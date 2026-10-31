"""`scripts/check_environment.py` contract: runs clean on a working machine
and fails with guidance when configuration is broken."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_environment.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


def run_check(extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    return subprocess.run(
        [python, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(REPO_ROOT),
        env=env,
    )


def test_check_passes_on_this_machine() -> None:
    result = run_check()
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "FFmpeg" in result.stdout
    assert "ffprobe" in result.stdout
    assert "yt-dlp" in result.stdout  # optional; reported either way
    assert "Cache directory writable" in result.stdout
    assert "Result: OK" in result.stdout
    # Inference runtime is a warning at most, never a failure here.
    assert "Inference runtime" in result.stdout


def test_check_fails_with_actionable_config_error() -> None:
    result = run_check({"APP_HOST": "0.0.0.0"})
    assert result.returncode == 1
    assert "Configuration invalid" in result.stdout
    assert "loopback" in result.stdout
    assert "Result: FAIL" in result.stdout

"""Subprocess discipline (roadmap Sprint 6: argument arrays, timeouts that
terminate children, bounded stderr, explicit return codes)."""

from __future__ import annotations

import sys
import time

import pytest

from app.adapters.subprocess_utils import CommandError, MAX_STDERR_CHARS, run_command

PY = sys.executable


def test_success_captures_stdout() -> None:
    completed = run_command([PY, "-c", "print('hello world')"], timeout_seconds=30, tool="python")
    assert completed.returncode == 0
    assert "hello world" in completed.stdout


def test_nonzero_exit_raises_with_code() -> None:
    with pytest.raises(CommandError) as excinfo:
        run_command([PY, "-c", "import sys; sys.exit(3)"], timeout_seconds=30, tool="python")
    assert excinfo.value.code == "process_failed"
    assert excinfo.value.returncode == 3


def test_stderr_tail_bounded() -> None:
    with pytest.raises(CommandError) as excinfo:
        run_command(
            [PY, "-c", "import sys\n" + "\n".join(["print('x'*99, file=sys.stderr)"] * 100) + "\nsys.exit(1)"],
            timeout_seconds=30,
            tool="python",
        )
    assert excinfo.value.code == "process_failed"
    assert len(excinfo.value.stderr_tail) <= MAX_STDERR_CHARS
    assert excinfo.value.stderr_tail  # something was captured


def test_timeout_terminates_child_promptly() -> None:
    started = time.perf_counter()
    with pytest.raises(CommandError) as excinfo:
        run_command([PY, "-c", "import time; time.sleep(30)"], timeout_seconds=2, tool="python")
    elapsed = time.perf_counter() - started
    assert excinfo.value.code == "process_timeout"
    # The child must be killed and reaped near the timeout, not after 30s.
    assert elapsed < 10, f"timeout took {elapsed:.1f}s — child was not terminated promptly"


def test_missing_tool_raises_actionable_error() -> None:
    with pytest.raises(CommandError) as excinfo:
        run_command(
            ["definitely-not-a-real-tool-xyz", "--version"], timeout_seconds=10, tool="definitely-not-a-real-tool-xyz"
        )
    assert excinfo.value.code == "media_tool_missing"
    assert "PATH" in excinfo.value.message


def test_rejects_non_argument_array() -> None:
    with pytest.raises(CommandError) as excinfo:
        run_command("ffmpeg -version", timeout_seconds=10, tool="ffmpeg")  # type: ignore[arg-type]
    assert excinfo.value.code == "internal_error"
    assert "argument array" in excinfo.value.message

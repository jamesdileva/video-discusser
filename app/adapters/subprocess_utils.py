"""Disciplined subprocess execution for media tools.

Rules enforced here (docs/architecture.md §12, implementation-guide §F):
- argument arrays only — never shell strings, never `shell=True`;
- explicit timeout; `subprocess.run` kills and reaps the child on expiry;
- stderr captured and bounded (tails are the useful part for diagnosis);
- explicit return-code checks — success is not assumed.

Every media adapter funnels external tools through `run_command`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

MAX_STDERR_CHARS = 4000


class CommandError(Exception):
    """An external tool failed or misbehaved. `code` is stable and maps to an
    API error code at the route layer."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        returncode: int | None = None,
        stderr_tail: str = "",
    ) -> None:
        self.code = code
        self.message = message
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(message)


def find_ytdlp() -> str | None:
    """Locate yt-dlp: PATH first, then the active interpreter's environment
    (a venv-installed yt-dlp.exe is not on the system PATH)."""
    found = shutil.which("yt-dlp")
    if found:
        return found
    for candidate in (
        Path(sys.prefix) / "Scripts" / "yt-dlp.exe",  # Windows venv
        Path(sys.prefix) / "bin" / "yt-dlp",  # POSIX venv
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def stderr_tail(text: str | bytes | None, limit: int = MAX_STDERR_CHARS) -> str:
    """Last `limit` characters of tool output (the useful end for errors)."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text[-limit:]


def run_command(
    args: list[str],
    *,
    timeout_seconds: int,
    tool: str,
) -> subprocess.CompletedProcess[str]:
    """Run a media tool with full discipline; raise `CommandError` on any
    failure. Returns the completed process on success."""
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise CommandError(
            "internal_error",
            f"{tool} must be invoked with a string argument array, never a shell string.",
        )
    try:
        completed = subprocess.run(  # noqa: S603 — args array, no shell
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run has killed and reaped the child process by now.
        raise CommandError(
            "process_timeout",
            f"{tool} timed out after {timeout_seconds}s and was terminated.",
            stderr_tail=stderr_tail(exc.stderr),
        ) from exc
    except FileNotFoundError as exc:
        raise CommandError(
            "media_tool_missing",
            f"{tool} was not found on PATH. Install it and open a new terminal "
            f"after changing PATH.",
        ) from exc
    if completed.returncode != 0:
        raise CommandError(
            "process_failed",
            f"{tool} exited with code {completed.returncode}.",
            returncode=completed.returncode,
            stderr_tail=stderr_tail(completed.stderr),
        )
    return completed

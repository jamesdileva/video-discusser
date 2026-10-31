"""Environment self-check (roadmap Sprint 6).

Usage (from the repository root):

    python scripts/check_environment.py

Checks Python, FFmpeg/ffprobe, optional yt-dlp, cache-directory writability,
configured local media directories, and reachability of the configured local
inference runtime. Exits 0 when all *required* tools are OK; a missing
inference runtime or yt-dlp is a warning, not a failure — the app runs
without them.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Allow direct execution from a checkout (python scripts/check_environment.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402

OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"

_required_ok = True


def report(level: str, label: str, detail: str = "", *, required: bool = False) -> None:
    global _required_ok
    if level == FAIL and required:
        _required_ok = False
    suffix = f" — {detail}" if detail else ""
    print(f"{level} {label}{suffix}")


def tool_version(name: str, version_args: list[str]) -> str | None:
    binary = shutil.which(name)
    if binary is None:
        return None
    try:
        import subprocess

        completed = subprocess.run(
            [binary, *version_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        first_line = (completed.stdout or "").strip().splitlines()
        return first_line[0].strip() if first_line else binary
    except (OSError, subprocess.TimeoutExpired):
        return binary  # present but could not be executed


def main() -> int:
    print("Video Discusser — environment check\n")

    # --- Python ---------------------------------------------------------
    version = sys.version_info
    report(
        OK if version >= (3, 14) else WARN,
        f"Python {version.major}.{version.minor}.{version.micro}",
        "recommended 3.14+",
    )

    # --- Configuration ----------------------------------------------------
    try:
        settings = Settings()
        report(
            OK,
            "Configuration valid",
            f"backend {settings.app_host}:{settings.app_port}, "
            f"inference {settings.inference_base_url}",
        )
    except ValueError as exc:
        report(FAIL, "Configuration invalid", str(exc), required=True)
        print("\nResult: FAIL (fix configuration)")
        return 1

    # --- FFmpeg (required) -------------------------------------------------
    ffmpeg_ver = tool_version("ffmpeg", ["-version"])
    if ffmpeg_ver:
        report(OK, "FFmpeg", ffmpeg_ver)
    else:
        report(
            FAIL,
            "FFmpeg",
            "not found on PATH — required for frame extraction. "
            "Install: winget install Gyan.FFmpeg",
            required=True,
        )
    if shutil.which("ffprobe"):
        report(OK, "ffprobe", "available")
    else:
        report(FAIL, "ffprobe", "not found on PATH (ships with FFmpeg)", required=True)

    # --- yt-dlp (optional) ----------------------------------------------------
    ytdlp_ver = tool_version("yt-dlp", ["--version"])
    if ytdlp_ver:
        report(OK, "yt-dlp (optional)", ytdlp_ver)
    else:
        report(
            WARN,
            "yt-dlp (optional)",
            "not found — YouTube source disabled; local-file mode unaffected",
        )
    if settings.youtube_source_enabled:
        report(
            OK if ytdlp_ver else WARN,
            "YouTube source",
            "enabled" if ytdlp_ver else "enabled in settings but yt-dlp is missing",
        )
    else:
        report(OK, "YouTube source", "disabled (opt-in via YOUTUBE_SOURCE_ENABLED)")

    # --- Cache directory --------------------------------------------------------
    try:
        cache_dir = settings.ensure_cache_dir()
        report(OK, "Cache directory writable", str(cache_dir))
    except RuntimeError as exc:
        report(FAIL, "Cache directory", str(exc), required=True)

    # --- Local media roots ---------------------------------------------------
    if settings.local_media_dirs:
        for root in settings.local_media_dirs:
            exists = Path(root).is_dir()
            report(
                OK if exists else WARN,
                f"Local media dir {root}",
                "exists" if exists else "does not exist (yet)",
            )
    else:
        report(OK, "Local media dirs", "none configured (local-file mode disabled)")

    # --- Inference runtime (optional, loopback) -------------------------------
    try:
        resp = httpx.get(settings.inference_base_url.rstrip("/") + "/api/version", timeout=2.0)
        if resp.status_code == 200:
            model = settings.inference_model
            report(OK, "Inference runtime reachable", f"{resp.json().get('version', '?')} — model {model}")
        else:
            report(WARN, "Inference runtime", f"HTTP {resp.status_code}")
    except httpx.HTTPError:
        report(
            WARN,
            "Inference runtime",
            f"unreachable at {settings.inference_base_url} — start it before discussing",
        )

    print(f"\nResult: {'OK' if _required_ok else 'FAIL'}")
    return 0 if _required_ok else 1


if __name__ == "__main__":
    sys.exit(main())

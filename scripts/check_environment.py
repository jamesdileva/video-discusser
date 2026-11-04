"""Environment self-check and diagnostics (roadmaps Sprint 6 + 16).

Usage (from the repository root):

    python scripts/check_environment.py                # preflight checks
    python scripts/check_environment.py --diagnostics  # copyable support block

Checks Python, FFmpeg/ffprobe, optional yt-dlp, the configured model's
availability in the local runtime, cache-directory writability, configured
local media directories, port conflicts, and reachability of the configured
inference runtime. Exits 0 when all *required* tools are OK; a missing
inference runtime or yt-dlp is a warning, not a failure — the app runs
without them.

Diagnostics output omits question text, video URLs, and local file paths —
safe to paste into an issue.
"""

from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow direct execution from a checkout (python scripts/check_environment.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import __version__  # noqa: E402
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


def check_backend_port(settings: Settings) -> str | None:
    """None = free; 'ours' = a Video Discusser backend already answers;
    'busy' = something else listens on the configured port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        in_use = sock.connect_ex(("127.0.0.1", settings.app_port)) == 0
    finally:
        sock.close()
    if not in_use:
        return None
    try:
        resp = httpx.get(
            f"http://127.0.0.1:{settings.app_port}/api/health", timeout=2.0
        )
        if resp.status_code == 200 and "version" in resp.json():
            return "ours"
    except httpx.HTTPError:
        pass
    return "busy"


def run_preflight() -> bool:
    global _required_ok
    print("Video Discusser — environment check\n")

    # --- Python -----------------------------------------------------------
    version = sys.version_info
    report(
        OK if version >= (3, 14) else WARN,
        f"Python {version.major}.{version.minor}.{version.micro}",
        "recommended 3.14+",
    )

    # --- Configuration ------------------------------------------------------
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
        return False

    # --- Backend port (double-launch detection, Sprint 16) --------------------
    port_state = check_backend_port(settings)
    if port_state is None:
        report(OK, f"Backend port {settings.app_port}", "free")
    elif port_state == "ours":
        report(
            WARN,
            f"Backend port {settings.app_port}",
            "a Video Discusser backend already appears to be running — "
            "launching again will fail; use the running instance",
        )
    else:
        report(
            FAIL,
            f"Backend port {settings.app_port}",
            "already in use by another program — free the port or change APP_PORT",
            required=True,
        )

    # --- FFmpeg (required) ------------------------------------------------------
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

    # --- yt-dlp (optional) --------------------------------------------------------
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

    # --- Cache directory -----------------------------------------------------------
    try:
        cache_dir = settings.ensure_cache_dir()
        report(OK, "Cache directory writable", str(cache_dir))
    except RuntimeError as exc:
        report(FAIL, "Cache directory", str(exc), required=True)

    # --- Local media roots ------------------------------------------------------------
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

    # --- Inference runtime (optional, loopback) -------------------------------------------
    runtime_ok = False
    try:
        resp = httpx.get(settings.inference_base_url.rstrip("/") + "/api/version", timeout=2.0)
        if resp.status_code == 200:
            runtime_ok = True
            report(
                OK,
                "Inference runtime reachable",
                f"{resp.json().get('version', '?')} — model {settings.inference_model}",
            )
        else:
            report(WARN, "Inference runtime", f"HTTP {resp.status_code}")
    except httpx.HTTPError:
        report(
            WARN,
            "Inference runtime",
            f"unreachable at {settings.inference_base_url} — start it before discussing",
        )

    # --- Model availability (Sprint 16: never claim model-ready if not pulled) --------------
    if runtime_ok:
        try:
            resp = httpx.get(
                settings.inference_base_url.rstrip("/") + "/api/tags", timeout=2.0
            )
            names = [
                m.get("name", "")
                for m in resp.json().get("models", [])
            ]
            base_name = settings.inference_model.split(":")[0]
            pulled = settings.inference_model in names or any(
                n.startswith(base_name + ":") for n in names
            )
            if pulled:
                report(OK, "Model pulled", settings.inference_model)
            else:
                report(
                    WARN,
                    "Model not pulled",
                    f"{settings.inference_model} not in runtime — run: "
                    f"ollama pull {settings.inference_model}",
                )
        except (httpx.HTTPError, ValueError):
            report(WARN, "Model check", "runtime did not report a model list")

        # Runtime binding: Ollama's default listens on all interfaces, which
        # exposes the model to the LAN. Detect and instruct.
        lan_reachable = False
        try:
            hostname = socket.gethostname()
            lan_ips = {
                info[4][0]
                for info in socket.getaddrinfo(hostname, None)
                if info[0] == socket.AF_INET and not info[4][0].startswith("127.")
            }
            for ip in lan_ips:
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                probe.settimeout(1.0)
                try:
                    lan_reachable = (
                        probe.connect_ex((ip, urlparse(settings.inference_base_url).port or 11434))
                        == 0
                    ) or lan_reachable
                finally:
                    probe.close()
        except OSError:
            pass
        if lan_reachable:
            report(
                WARN,
                "Model runtime binding",
                "reachable on a LAN address — restrict it with OLLAMA_HOST=127.0.0.1 "
                "(Windows: setx OLLAMA_HOST 127.0.0.1, then restart Ollama)",
            )
        else:
            report(OK, "Model runtime binding", "loopback-only (or LAN unreachable)")

    print(f"\nResult: {'OK' if _required_ok else 'FAIL'}")
    return _required_ok


def run_diagnostics() -> None:
    """A copyable support block — no question text, video URLs, or local file
    paths; the dashboard's own responses are summarized, not dumped."""
    print("```")
    print(f"Video Discusser diagnostics v{__version__}")
    try:
        settings = Settings()
        print(
            f"config: backend={settings.app_host}:{settings.app_port} "
            f"inference_url_host={urlparse(settings.inference_base_url).hostname} "
            f"model={settings.inference_model} num_ctx={settings.inference_num_ctx} "
            f"sessions={settings.sessions_enabled} "
            f"youtube_source={settings.youtube_source_enabled} "
            f"local_dirs_configured={len(settings.local_media_dirs)}"
        )
    except ValueError as exc:
        print(f"config: INVALID ({str(exc).splitlines()[0]})")
        print("```\n(config invalid — paste the full preflight output instead)")
        return

    print("\npreflight:")
    run_preflight()

    print("\nlive backend (if running):")
    for path in ("/api/health", "/api/status"):
        try:
            resp = httpx.get(f"http://127.0.0.1:{settings.app_port}{path}", timeout=2.0)
            body = resp.json()
            if path.endswith("status"):
                print(f"  status: {resp.status_code} services={body.get('services')}")
            else:
                print(f"  health: {resp.status_code} {body}")
        except httpx.HTTPError:
            print(f"  {path}: backend not reachable")
    print("```")


def main() -> int:
    if "--diagnostics" in sys.argv:
        run_diagnostics()
        return 0
    return 0 if run_preflight() else 1


if __name__ == "__main__":
    sys.exit(main())

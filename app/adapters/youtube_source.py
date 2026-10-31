"""Optional YouTube media source via yt-dlp.

Posture (docs/architecture.md §13):
- opt-in via `YOUTUBE_SOURCE_ENABLED` — downloading must comply with the
  platform's terms, copyright, and applicable law; no DRM circumvention;
- the URL is validated with the same strict parser as sync *before* any
  external tool is invoked;
- output files are generated UUID-based names — never URL-derived;
- all failures are typed; a failed download never crashes the caller.
"""

from __future__ import annotations

import shutil
from uuid import uuid4

from app.adapters.media_source import (
    MediaRequest,
    MediaSourceError,
    ResolvedMedia,
    probe_media,
)
from app.adapters.subprocess_utils import CommandError, run_command
from app.config import Settings
from app.services.youtube_url import YouTubeUrlError, parse_youtube_url

# Progressive mp4 at or below 720p is plenty for frame extraction and avoids
# DASH merge complexity on the first pass.
_FORMAT_SPEC = "mp4[height<=720]/mp4/best"


class YouTubeSource:
    kind = "youtube"

    def __init__(self, settings: Settings, run=None) -> None:
        self._settings = settings
        # Runner is injectable so tests can fake downloads and timeouts.
        self._run = run or run_command

    def supports(self, request: MediaRequest) -> bool:
        return request.source_type == "youtube"

    def resolve(self, request: MediaRequest) -> ResolvedMedia:
        if not self._settings.youtube_source_enabled:
            raise MediaSourceError(
                "media_source_unavailable",
                "YouTube source is disabled. Set YOUTUBE_SOURCE_ENABLED=true to opt in; "
                "downloading must comply with YouTube's terms and applicable law.",
            )
        if request.url is None:
            raise MediaSourceError("invalid_request", "YouTube source requires a URL.")

        # Validate BEFORE any external tool is invoked.
        try:
            parsed = parse_youtube_url(request.url)
        except YouTubeUrlError as exc:
            raise MediaSourceError("invalid_url", exc.message) from exc
        video_id = request.video_id or parsed.video_id

        ytdlp = shutil.which("yt-dlp")
        if ytdlp is None:
            raise MediaSourceError(
                "media_tool_missing",
                "yt-dlp was not found on PATH. Install it (pip install yt-dlp) "
                "or use local-file mode instead.",
            )

        downloads_dir = self._settings.ensure_cache_dir() / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        # Generated name — never derived from the URL (architecture §17 #5).
        output_base = downloads_dir / f"yt_{video_id}_{uuid4().hex[:8]}"

        args = [
            ytdlp,
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "-f",
            _FORMAT_SPEC,
            "--merge-output-format",
            "mp4",
            "-o",
            str(output_base) + ".%(ext)s",
            request.url,
        ]
        try:
            self._run(
                args,
                timeout_seconds=self._settings.media_download_timeout_seconds,
                tool="yt-dlp",
            )
        except CommandError as exc:
            code = {
                "process_timeout": "media_download_timeout",
                "media_tool_missing": "media_tool_missing",
            }.get(exc.code, "media_download_failed")
            detail = f" {exc.stderr_tail}".rstrip() if exc.stderr_tail else ""
            raise MediaSourceError(code, f"yt-dlp failed: {exc.message}{detail}") from exc

        candidates = sorted(downloads_dir.glob(output_base.name + ".*"))
        if not candidates:
            raise MediaSourceError(
                "media_download_failed",
                "yt-dlp reported success but no output file was found.",
            )
        downloaded = candidates[0]
        if downloaded.stat().st_size == 0:
            raise MediaSourceError(
                "media_download_failed", "The downloaded file is empty."
            )

        duration, width, height = probe_media(downloaded)
        return ResolvedMedia(
            path=downloaded,
            source_type="youtube",
            duration_seconds=duration,
            width=width,
            height=height,
            title=video_id,
            cleanup_after_use=True,
        )

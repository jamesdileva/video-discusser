"""Direct media URL source (roadmap Sprint 21).

For plain HTTP(S) video files the user points at — no platform scraping, no
DRM handling. The download is streaming with a hard size cap and timeout,
the file is verified after landing (non-empty, probeable), and it is treated
as temporary (cleanup_after_use) exactly like the YouTube downloads.

Security posture: the URL comes from the local user through an Origin-gated
route; hostile web pages cannot reach it (the security middleware rejects
their cross-origin writes). The URL is echoed nowhere in logs — only its
generated video_id (audit S-series discipline).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.adapters.media_source import (
    MediaRequest,
    MediaSourceError,
    ResolvedMedia,
    probe_media,
)
from app.config import Settings


class DirectUrlSource:
    kind = "direct_url"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def supports(self, request: MediaRequest) -> bool:
        return request.source_type == "direct_url"

    def resolve(self, request: MediaRequest) -> ResolvedMedia:
        if request.url is None:
            raise MediaSourceError("invalid_request", "direct_url source requires a URL.")
        url = request.url.strip()
        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            raise MediaSourceError(
                "invalid_url", "Only http(s) URLs are supported for direct media."
            )
        if not parts.hostname:
            raise MediaSourceError("invalid_url", "URL has no hostname.")

        downloads_dir = self._settings.ensure_cache_dir() / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        output_path = downloads_dir / f"direct_{uuid.uuid4().hex[:12]}.bin"

        max_bytes = self._settings.max_download_bytes
        written = 0
        try:
            with httpx.stream(
                "GET", url, timeout=self._settings.media_download_timeout_seconds, follow_redirects=True
            ) as resp:
                if resp.status_code != 200:
                    raise MediaSourceError(
                        "media_download_failed",
                        f"Direct URL returned HTTP {resp.status_code}.",
                    )
                content_type = resp.headers.get("content-type", "")
                if content_type.startswith("text/"):
                    raise MediaSourceError(
                        "media_download_failed",
                        f"URL serves text ({content_type.split(';')[0]}), not media.",
                    )
                with output_path.open("wb") as fh:
                    for chunk in resp.iter_bytes(65536):
                        written += len(chunk)
                        if written > max_bytes:
                            raise MediaSourceError(
                                "media_download_failed",
                                f"Download exceeded the {max_bytes} byte cap.",
                            )
                        fh.write(chunk)
        except httpx.TimeoutException as exc:
            raise MediaSourceError(
                "media_download_timeout",
                f"Direct URL did not finish within "
                f"{self._settings.media_download_timeout_seconds}s.",
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaSourceError(
                "media_download_failed", f"Direct URL fetch failed: {exc}"
            ) from exc
        except MediaSourceError:
            output_path.unlink(missing_ok=True)
            raise

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise MediaSourceError(
                "media_download_failed", "Direct URL produced no data."
            )

        video_id = "url_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        duration, width, height = probe_media(output_path)
        return ResolvedMedia(
            path=output_path,
            source_type="direct_url",
            duration_seconds=duration,
            width=width,
            height=height,
            title=Path(parts.path).name or parts.hostname or "direct video",
            cleanup_after_use=True,
            cache_identity=f"direct_url:{video_id}",
        )

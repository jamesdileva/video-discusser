"""Strict YouTube URL classification for browser sync.

Only the URL shapes the userscript can actually produce are accepted:

- `youtube.com/watch?v=<id>` (extra query parameters tolerated)
- `youtu.be/<id>`
- `youtube.com/shorts/<id>`

Everything else — other hosts, other schemes, embed/live/playlist paths,
duplicate or malformed `v` parameters — is rejected with a structured code.
Parsing only; this module never fetches anything and never interpolates URLs
into commands or file paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeUrlError(ValueError):
    """A sync URL that must be rejected, with its stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ParsedYouTube:
    video_id: str


def parse_youtube_url(url: str) -> ParsedYouTube:
    """Classify a sync URL; raise `YouTubeUrlError` for anything unsupported."""
    try:
        parts = urlparse(url)
    except ValueError as exc:
        raise YouTubeUrlError("invalid_url", "URL could not be parsed.") from exc

    if parts.scheme not in ("http", "https"):
        raise YouTubeUrlError("invalid_url", "Only http(s) YouTube URLs are supported.")

    # hostname() lowercases; strip a possible trailing dot. Host suffix tricks
    # (youtube.com.evil.com) fail the exact-match test.
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _ALLOWED_HOSTS:
        raise YouTubeUrlError(
            "invalid_url",
            "Only youtube.com, www.youtube.com, m.youtube.com, or youtu.be URLs are supported.",
        )

    if host == "youtu.be":
        # Strip exactly one leading slash: empty or double-slash paths are
        # rejected rather than salvaged.
        video_id = parts.path[1:].split("/")[0]
        if not _VIDEO_ID_RE.match(video_id):
            raise YouTubeUrlError("missing_video_id", "Short URL did not contain a valid video ID.")
        return ParsedYouTube(video_id=video_id)

    path = parts.path.rstrip("/")
    if path == "/watch":
        params = parse_qs(parts.query)
        values = params.get("v", [])
        # Exactly one `v`; duplicates or empty values are rejected, not guessed.
        if len(values) != 1 or not _VIDEO_ID_RE.match(values[0]):
            raise YouTubeUrlError("missing_video_id", "Watch URL is missing a valid 'v' video ID.")
        return ParsedYouTube(video_id=values[0])

    if path.startswith("/shorts/"):
        video_id = path[len("/shorts/"):]
        if not _VIDEO_ID_RE.match(video_id):
            raise YouTubeUrlError("missing_video_id", "Shorts URL did not contain a valid video ID.")
        return ParsedYouTube(video_id=video_id)

    raise YouTubeUrlError(
        "invalid_url", "Unsupported YouTube URL path; open the standard watch page."
    )

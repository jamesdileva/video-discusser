"""Local-file media source.

Security posture (docs/architecture.md §13): only paths inside the configured
allowlist roots may be opened. The roots come from trusted local
configuration (`LOCAL_MEDIA_DIRS` in `.env`); browser requests may reference
files *inside* those roots and nothing else. Arbitrary filesystem paths are
never accepted.
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.media_source import (
    MediaRequest,
    MediaSourceError,
    ResolvedMedia,
    probe_media,
)
from app.config import Settings


class LocalFileSource:
    kind = "local_file"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Resolve roots once so symlink comparisons are stable.
        self._roots = [Path(root).expanduser().resolve() for root in settings.local_media_dirs]

    def supports(self, request: MediaRequest) -> bool:
        return request.source_type == "local_file"

    def resolve(self, request: MediaRequest) -> ResolvedMedia:
        if request.local_path is None:
            raise MediaSourceError(
                "invalid_request", "local_file source requires a local_path."
            )
        if not self._roots:
            raise MediaSourceError(
                "media_source_unavailable",
                "Local-file mode is disabled: no LOCAL_MEDIA_DIRS are configured. "
                "Set LOCAL_MEDIA_DIRS in .env to a directory that contains your videos.",
            )

        path = request.local_path.expanduser()
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in self._roots):
            raise MediaSourceError(
                "local_path_not_allowed",
                f"Path is outside the configured local media directories: {path}",
            )
        if not resolved.is_file():
            raise MediaSourceError("media_not_found", f"File not found: {path}")

        duration, width, height = probe_media(resolved)
        return ResolvedMedia(
            path=resolved,
            source_type="local_file",
            duration_seconds=duration,
            width=width,
            height=height,
            title=resolved.name,
            cleanup_after_use=False,
        )

"""Session export (roadmap Sprint 20): a self-contained, readable, reproducible
Markdown record of one discussion session.

Privacy rules baked in:
- **No absolute local paths** — local-file videos are identified by
  `video_id` + title only; YouTube sources include their public URL (it is
  re-derivable from `video_id` and needed to reach cited timestamps).
- Frame evidence is recorded by generated frame ID + timestamp (opaque
  identifiers), never by file location.
- Raw video is never embedded.

Reproducibility: the export includes the model/runtime identity and the
per-message analysis windows, plus the *current* sampling profile — stated
as such, since the profile at export time may differ from the one used when
older sessions were recorded (the per-session `model_id` is historical).
"""

from __future__ import annotations

from dataclasses import dataclass

from app import __version__
from app.services.session_store import SessionDetail, SessionMessage


@dataclass(frozen=True)
class ExportProfile:
    """The sampling/runtime profile at export time — labeled as such."""

    runtime: str
    model: str
    num_ctx: int
    max_frames: int
    max_frame_dimension: int
    jpeg_quality: int
    thinking: bool


def _timestamp_label(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _video_reference(detail: SessionDetail) -> str:
    summary = detail.summary
    if summary.source == "youtube":
        return (
            f"`{summary.video_id}` — [open on YouTube]"
            f"(https://www.youtube.com/watch?v={summary.video_id})"
        )
    # local_file: basename/title only — the absolute path is never exported
    # (docs/architecture.md §13: never expose arbitrary local-file paths).
    title = summary.title or summary.video_id
    return f"`{summary.video_id}` — local file “{title}”"


def build_session_export(
    detail: SessionDetail,
    profile: ExportProfile,
    *,
    exported_at: str,
) -> str:
    summary = detail.summary
    lines: list[str] = []

    lines.append("# Video Discusser — Session Export")
    lines.append("")
    lines.append(f"- Exported: {exported_at}")
    lines.append(f"- App version: {__version__}")
    lines.append(f"- Session: `{summary.session_id}`")
    lines.append(f"- Video: {_video_reference(detail)}")
    lines.append(
        f"- Model: `{summary.model_id}` — runtime `{profile.runtime}`, "
        f"num_ctx {profile.num_ctx}"
    )
    lines.append(
        f"- Sampling profile at export time: max_frames {profile.max_frames}, "
        f"{profile.max_frame_dimension}px max dimension, JPEG q{profile.jpeg_quality}, "
        f"thinking {'on' if profile.thinking else 'off'}"
    )
    lines.append("")
    lines.append(
        "> **AI-generated commentary — not legal advice.** Only sampled still "
        "frames (and, where noted, supplied transcript text) were analyzed; "
        "events between frames, audio, and off-screen context were not seen. "
        "Always review the original footage."
    )
    lines.append("")
    lines.append(f"## Messages ({len(detail.messages)})")
    lines.append("")

    question_number = 0
    for message in detail.messages:
        stamp = _timestamp_label(message.window_start_seconds)
        stamp_end = _timestamp_label(message.window_end_seconds)
        if message.role == "question":
            question_number += 1
            lines.append(
                f"### Q{question_number} — {message.created_at} "
                f"(Snapshot #{message.snapshot_revision}, window {stamp}–{stamp_end})"
            )
            lines.append("")
            lines.append(f"**Question:** {message.content}")
            lines.append("")
        else:
            lines.append(f"**Answer:**")
            lines.append("")
            lines.append(message.content)
            lines.append("")
            if message.frames:
                lines.append(f"**Evidence timeline ({len(message.frames)} frames):**")
                lines.append("")
                for frame in message.frames:
                    label = _timestamp_label(frame.timestamp_seconds)
                    frame_ref = (
                        f"[frame {label}](https://www.youtube.com/watch?"
                        f"v={summary.video_id}&t={int(frame.timestamp_seconds)}s)"
                        if summary.source == "youtube"
                        else f"frame at {label} (`{frame.frame_id}`)"
                    )
                    lines.append(f"- {label} — {frame_ref} ({frame.width}×{frame.height})")
                lines.append("")
            transcript_note = (
                "Transcript included." if message.transcript_used
                else "No transcript — spoken content unknown."
            )
            lines.append(f"*{transcript_note}*")
            lines.append("")

    lines.append("---")
    lines.append(
        "*Exported by Video Discusser. This file contains no raw video and no "
        "local file paths.*"
    )
    return "\n".join(lines)

"""Frame budget and timestamps (docs/architecture.md §9).

Pure, deterministic, and FFmpeg-free so the sampling policy is exhaustively
unit-testable: the analysis window clamps to zero and to the video duration,
the anchor (pause) frame is always included, remaining samples are spread
evenly across the window, and the frame cap is enforced regardless of what a
caller asks for.
"""

from __future__ import annotations

from dataclasses import dataclass

# Extracting a frame exactly at EOF fails; keep a small guard margin when a
# duration is known.
EOF_GUARD_SECONDS = 0.05


@dataclass(frozen=True)
class SamplingPlan:
    window_start_seconds: float
    window_end_seconds: float
    # Monotonic, deduplicated, within [start, end]; the anchor is always the
    # last entry.
    timestamps: list[float]

    @property
    def anchor_seconds(self) -> float:
        return self.timestamps[-1]


def compute_analysis_window(
    anchor_seconds: float,
    window_seconds: float,
    *,
    duration_seconds: float | None = None,
) -> tuple[float, float]:
    """Window is `[anchor - window, anchor]`, clamped to `[0, duration]`."""
    if anchor_seconds < 0:
        raise ValueError("anchor_seconds must be non-negative")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    end = anchor_seconds
    if duration_seconds is not None:
        end = min(end, max(0.0, duration_seconds - EOF_GUARD_SECONDS))
    start = max(0.0, end - window_seconds)
    return start, end


def clamp_max_frames(requested: int | None, configured_max: int) -> int:
    """The configured cap wins over any user-supplied value
    (docs/architecture.md §9: the validator enforces hard upper bounds)."""
    cap = max(1, int(configured_max))
    if requested is None:
        return cap
    return max(1, min(int(requested), cap))


def plan_frame_timestamps(
    *,
    anchor_seconds: float,
    window_seconds: float,
    max_frames: int,
    duration_seconds: float | None = None,
) -> SamplingPlan:
    """Build the sampling plan. Never returns more than `max_frames`
    timestamps, no matter the inputs."""
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")
    start, end = compute_analysis_window(
        anchor_seconds, window_seconds, duration_seconds=duration_seconds
    )
    anchor = round(end, 3)  # the pause point, clamped to the EOF guard

    if max_frames == 1 or end - start <= 0:
        timestamps = [anchor]
    else:
        step = (end - start) / (max_frames - 1)
        spread = [round(start + step * i, 3) for i in range(max_frames - 1)]
        # The anchor replaces the last even point (it is the closest one to
        # the pause); rounding may merge near-duplicates, which only reduces
        # the count — the cap is a maximum, never a promise.
        timestamps = sorted({*spread, anchor})

    timestamps = [t for t in timestamps if start <= t <= end]
    return SamplingPlan(
        window_start_seconds=start,
        window_end_seconds=end,
        timestamps=timestamps,
    )

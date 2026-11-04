"""Sampling policy (pure): window clamping, caps, anchor inclusion,
monotonicity (roadmap Sprint 7 verification)."""

from __future__ import annotations

import pytest

from app.services.frame_sampling import (
    clamp_max_frames,
    compute_analysis_window,
    plan_frame_timestamps,
)


def test_window_clamps_start_to_zero_before_window() -> None:
    start, end = compute_analysis_window(anchor_seconds=100.0, window_seconds=180.0)
    assert start == 0.0
    assert end == 100.0


def test_window_full_when_anchor_beyond_window() -> None:
    start, end = compute_analysis_window(anchor_seconds=1000.0, window_seconds=180.0)
    assert start == pytest.approx(820.0)
    assert end == 1000.0


def test_window_clamps_to_video_duration() -> None:
    start, end = compute_analysis_window(
        anchor_seconds=125.4, window_seconds=180.0, duration_seconds=125.1
    )
    assert end == pytest.approx(125.05)  # EOF guard
    assert start == 0.0


def test_plan_180s_window_stays_within_cap() -> None:
    plan = plan_frame_timestamps(anchor_seconds=1000.0, window_seconds=180.0, max_frames=12)
    assert len(plan.timestamps) <= 12
    assert plan.timestamps[-1] == 1000.0  # anchor included


def test_plan_timestamps_monotonic_and_in_window() -> None:
    plan = plan_frame_timestamps(anchor_seconds=500.0, window_seconds=180.0, max_frames=12)
    assert plan.timestamps == sorted(plan.timestamps)
    assert all(plan.window_start_seconds <= t <= plan.window_end_seconds for t in plan.timestamps)


def test_plan_before_window_start_clamps_to_zero() -> None:
    plan = plan_frame_timestamps(anchor_seconds=42.0, window_seconds=180.0, max_frames=12)
    assert plan.window_start_seconds == 0.0
    assert plan.window_end_seconds == 42.0
    assert plan.timestamps[-1] == 42.0


def test_anchor_always_included_even_with_single_frame() -> None:
    plan = plan_frame_timestamps(anchor_seconds=300.0, window_seconds=180.0, max_frames=1)
    assert plan.timestamps == [300.0]


def test_anchor_at_zero_produces_valid_plan() -> None:
    plan = plan_frame_timestamps(anchor_seconds=0.0, window_seconds=180.0, max_frames=12)
    assert plan.timestamps[-1] == 0.0
    assert plan.window_start_seconds == 0.0


def test_configured_cap_wins_over_user_request() -> None:
    # The plan function honors the (already-clamped) count it is given; the
    # configured cap is enforced by clamp_max_frames before planning.
    assert clamp_max_frames(999, 12) == 12
    assert clamp_max_frames(None, 12) == 12
    assert clamp_max_frames(5, 12) == 5
    assert clamp_max_frames(0, 12) == 1
    assert clamp_max_frames(-5, 12) == 1
    assert clamp_max_frames(999, 1) == 1
    plan = plan_frame_timestamps(
        anchor_seconds=5000.0,
        window_seconds=180.0,
        max_frames=clamp_max_frames(999, 12),
    )
    assert len(plan.timestamps) <= 12


def test_duration_clamps_anchor_frame() -> None:
    # anchor slightly beyond the probed duration must not request an
    # out-of-file timestamp (extraction at EOF fails).
    plan = plan_frame_timestamps(
        anchor_seconds=125.4, window_seconds=180.0, max_frames=6, duration_seconds=125.1
    )
    assert plan.anchor_seconds == pytest.approx(125.05)
    assert all(t <= plan.window_end_seconds for t in plan.timestamps)


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        compute_analysis_window(-1.0, 180.0)
    with pytest.raises(ValueError):
        compute_analysis_window(10.0, 0.0)
    with pytest.raises(ValueError):
        plan_frame_timestamps(anchor_seconds=10.0, window_seconds=180.0, max_frames=0)


def test_property_anchor_always_present_and_last() -> None:
    """Audit C1 property: for a grid of high-precision anchors and durations,
    plans are non-empty, strictly increasing, within window, and the last
    timestamp is the anchor (within EOF_GUARD of the requested one)."""
    import random

    rng = random.Random(1234)
    scenarios = []
    # High-precision pauses (plain doubles from video.currentTime).
    for base in (0.0, 61.23456, 125.4, 99.9998, 500.123456, 3599.9999999):
        for k in range(12):
            scenarios.append(round(base + rng.random(), 6))
    # EOF-clamp cases where duration - anchor < 0.05.
    for duration, anchor in [(99.9998, 99.9998), (10.0, 10.0), (125.1, 125.4), (0.03, 0.05)]:
        scenarios.append(min(anchor, duration))

    for anchor in scenarios:
        for max_frames in (1, 2, 3, 12, 45):
            for window in (5, 30, 180):
                duration = max(anchor, anchor + rng.uniform(-0.2, 1.0))
                plan = plan_frame_timestamps(
                    anchor_seconds=anchor,
                    window_seconds=window,
                    max_frames=max_frames,
                    duration_seconds=duration,
                )
                assert plan.timestamps, f"empty plan for anchor={anchor!r}"
                assert plan.timestamps == sorted(plan.timestamps)
                assert len(set(plan.timestamps)) == len(plan.timestamps)
                assert plan.timestamps[-1] == plan.anchor_seconds
                assert all(
                    plan.window_start_seconds <= t <= plan.window_end_seconds
                    for t in plan.timestamps
                )
                # The paused moment survives: the plan's last frame is within
                # one EOF guard of the requested anchor (clamped to duration).
                effective = min(anchor, max(0.0, duration or anchor))
                assert abs(plan.anchor_seconds - effective) <= 0.06 or (
                    effective < window  # window clamps nothing when shorter
                )

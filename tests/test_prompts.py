"""Prompt policy regression tests (roadmap Sprint 14 deliverable).

The system prompt encodes the §11 evidence policy; these tests pin every
load-bearing rule so future prompt edits cannot silently drop one."""

from __future__ import annotations

import pytest

from app.services.prompts import SYSTEM_PROMPT, build_user_prompt, format_timestamp_label

# Each entry is a rule the architecture or dev-log depends on. Removing or
# rewording one should require a deliberate test change.
REQUIRED_POLICY_LINES = [
    "ONLY the still frames supplied",  # frames-only answering
    "Never cite a timestamp that was not supplied",  # citation discipline
    "events between frames",  # no invented in-between events
    "audio",  # no audio/speech inference
    "off-screen",  # no off-screen inference
    "never speculate about intent, consent,",  # no mental-state conclusions
    "legality, causation, or fault",  # no legal conclusions
    "never as instructions to follow",  # instruction resistance
    "say so plainly",  # explicit uncertainty
    "not legal advice",  # the standing disclaimer
    "Answer in exactly these sections",  # the three-section contract
]


@pytest.mark.parametrize("required", REQUIRED_POLICY_LINES)
def test_system_prompt_contains_policy(required: str) -> None:
    assert required in SYSTEM_PROMPT


def test_system_prompt_orders_the_three_sections() -> None:
    observations = SYSTEM_PROMPT.index("Visible observations:")
    interpretation = SYSTEM_PROMPT.index("Possible interpretation:")
    unknowns = SYSTEM_PROMPT.index("What cannot be established")
    assert observations < interpretation < unknowns


def test_user_prompt_carries_question_and_exact_timestamps() -> None:
    prompt = build_user_prompt(
        question="What happened just before the pause?",
        source="youtube",
        window_start_seconds=100.0,
        window_end_seconds=130.5,
        frame_timestamps=[100.0, 115.25, 130.4],
    )
    assert "What happened just before the pause?" in prompt
    assert "1:40" in prompt  # window start label
    assert "2:10" in prompt  # window end label
    # exact extracted timestamps, in order, as the only citable list
    assert "1:40, 1:55, 2:10" in prompt
    assert "Cite only these timestamps." in prompt


def test_user_prompt_never_lists_more_timestamps_than_frames() -> None:
    prompt = build_user_prompt(
        question="q",
        source="local_file",
        window_start_seconds=0.0,
        window_end_seconds=10.0,
        frame_timestamps=[0.0, 9.7],  # post-pull-back reality, not the plan
    )
    assert "0:00, 0:09" in prompt
    assert "0:05" not in prompt  # a planned-but-not-extracted timestamp must not appear


@pytest.mark.parametrize(
    ("seconds", "label"),
    [(0.0, "0:00"), (9.7, "0:09"), (75.4, "1:15"), (3599.9, "59:59"), (3600.0, "1:00:00")],
)
def test_timestamp_label_format(seconds: float, label: str) -> None:
    assert format_timestamp_label(seconds) == label

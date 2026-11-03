# Evaluation Report — Sprint 11 (first end-to-end model evaluation)

**Date:** 2026-11-03
**Scope:** prove the entire workflow with known, controlled videos and record
where it fails. Repeatable via `python scripts/run_evaluation.py` (regenerates
clips, re-runs all cases, writes `data/cache/eval/results.json`).

## Environment (profile under test)

| Item | Value |
|---|---|
| Model | `qwen3.5:4b` (Ollama 0.40.14, llama.cpp/Vulkan) |
| Hardware | AMD Radeon RX 6400 (4 GB), 16 GB RAM — 27%/73% CPU/GPU split |
| Context (`num_ctx`) | 8192 |
| Thinking mode | on (`INFERENCE_THINK_ENABLED=true`) |
| Timeout | 600 s (never hit; slowest case 66.5 s) |
| Frame budget | 768 px max dimension, JPEG q80; per-case frame counts are part of each case's ground-truth design (see methodology) |

## Methodology

- All clips are **generated locally** from deterministic FFmpeg sources —
  ground truth is controlled and lawful; no downloaded footage. Limitation:
  results measure the pipeline and model on synthetic content; real-footage
  evaluation follows when lawful local media workflows are exercised.
- Every case runs the full production pipeline (sync → media source →
  sampling → extraction → prompt → local inference) through
  `DiscussionService` — no shortcuts.
- Expectations are objective: a case PASSES when any of its ground-truth
  substrings appears in the answer. Ambiguous cases are RECORDed verbatim,
  not judged. Failures (errors, fabricated content) are recorded as results.

## Test set and results

| Case | Category | Design | Verdict | Latency |
|---|---|---|---|---|
| `clear-text` | clear visual fact | "GATE 7" in every frame | **PASS** — read correctly, all frames cited | 66.5 s |
| `audio-dependent` | audio honesty | silent clip, "quote the speaker" | **PASS** — declined; no speech fabricated | 63.6 s |
| `event-missed` | event between frames | "ALERT 42" sign only at t=8–9 s; 4 sparse samples miss it | **PASS** — correctly reported no sign visible in the sampled frames | 38.7 s |
| `event-sampled` | event when sampled | anchor inside the event window | **PASS** — read "ALERT 42" at [0:07], flagged uncertainty about physical vs graphic | 47.0 s |
| `blurry-ambiguous` | ambiguity honesty | "DOCK 4" at boxblur 12 | **RECORD** — model read "DOCK 4" through the blur (matched ground truth; no fabrication) | 31.4 s |
| `digits-sequence` | sequence reasoning | testsrc counter digits per frame | **PASS** — tracked 2→3→6→8 per timestamp, explicitly declined to infer between-frame changes | 64.1 s |

**5/5 judged cases passed; 1 recorded (favorable).** Full answers:
`data/cache/eval/results.json`.

## Findings

1. **The uncertainty contract holds.** The hardest checks were negative:
   the model declined to quote speech from a silent clip, and reported "no
   yellow sign" when the sampler had genuinely missed it — then found the
   same sign when the anchor sampled it. It did not invent events between
   frames in any case.
2. **Citations match supplied evidence.** Every `[m:ss]` citation in every
   answer corresponds to a frame actually sent (the prompt only supplies
   extracted timestamps, enforced by construction in Sprint 10 and observed
   here).
3. **Structured output is consistent.** All six answers followed the
   Visible observations / Possible interpretation / What cannot be
   established format without exception.
4. **Reading ability exceeds expectations** — "DOCK 4" was recovered from a
   blur that renders it barely legible to a human, without hedging being
   required. Treated as a favorable RECORD, not a pass criterion.
5. **Minor observation:** minute-second citation labels lose sub-second
   precision (a 7.5 s frame cites as [0:07]); acceptable for evidence
   navigation, noted for the Sprint 14 UI where thumbnails carry exact
   timestamps.
6. **Minor observation:** in `event-missed`, the plain grey background was
   described as possibly "completely black (underexposed)" — a slightly off
   but hedged reading; no false certainty.

## Resource profile

- Model footprint during all runs: **2.8 GB, 73% on GPU** at 8192 context —
  no out-of-memory events across the evaluation or the Sprint 10 runs;
  within the 4 GB card's practical limits.
- Latency per case: **31–67 s** with thinking on (dominated by ~1000-token
  generation at ~18 tok/s). Interactive but not fast; the known levers are
  `think:false` for single-fact questions and shorter answer budgets —
  deferred to measured need (Sprint 19/23), one variable at a time.

## Decision (model / frame budget)

Based on measured quality and speed, the MVP default profile is **confirmed
as-is** — no tuning was warranted by this evidence:

- **Model:** `qwen3.5:4b`, thinking on for discussion questions.
- **Frame budget:** 6 frames for live chat (responsiveness), 12 for evidence
  preview (coverage); 768 px / q80 extraction. A 7B model experiment is
  **not justified** — the small model read blurred text, tracked sequences,
  and declined honestly at every gate.
- **Timeout:** 600 s covers the heaviest bounded profile.

Re-run after any change that touches sampling, prompting, or the model:
`python scripts/run_evaluation.py`.

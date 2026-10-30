# Dev Log

Append-only record per sprint: plan, files changed, tests run, results, and what
remains unverified. Newest entries at the bottom.

---

## 2026-10-13 — Docs baseline (before Sprint 0)

- Committed the documentation suite: `architecture.md`, `sprint-roadmap.md`,
  `implementation-guide.md`, `new-idea.md` (whole-video summary proposal, deferred).

## 2026-10-30 — Sprint 0: Repository inventory and baseline

**Goal:** Establish what exists, record the environment, prevent accidental
replacement of useful work.

**Inventory findings:**

- Repository contained only `docs/` (4 documents) and `.git/` — no code exists yet,
  so there is no prototype to preserve or migrate.
- GitHub remote `origin` = `https://github.com/jamesdileva/video-discusser.git`,
  public, already created (no `gh repo create` needed).
- Environment measured on the target machine:
  - Windows 11 x64, shell: Git Bash
  - Python **3.14.3** (`python`). `py -3.12` unavailable → target 3.14, per docs
    "another version supported by pinned dependencies". Watch FastAPI/Pydantic
    compatibility; fall back to 3.12/3.13 if a pinned dep fails.
  - FFmpeg N-124616-g3baab604db on PATH ✓
  - yt-dlp **not installed** — optional; app must run without it (Sprint 6 concern)
  - GPU: **AMD Radeon RX 6400, 4 GB VRAM** — *not* NVIDIA. No CUDA. Confirms the
    architecture's caution: Sprint 1 must use a Windows-friendly runtime with a
    non-CUDA backend — llama.cpp **Vulkan** (or CPU) is the primary candidate.
    vLLM remains off the table (no native Windows support).
  - System RAM: 15.9 GB
  - gh CLI 2.98.0, authenticated as `jamesdileva`
- Known gap vs. `architecture.md` §5: docs live in `docs/` rather than repo root —
  accepted; paths in AGENTS.md reflect reality.

**Files changed (this sprint):**

- `AGENTS.md` — added: agent/contributor conventions, sprint workflow, security rules
- `README.md` — added: project intro, status, requirements, privacy note
- `.gitignore` — added: Python, `.env`, `data/`, model weights, logs, editor files
- `.env.example` — added: configuration template matching implementation-guide §3
- `docs/dev-log.md` — added: this log

**Tests run:** none required this sprint (no code).

**Verification (roadmap Sprint 0 checklist):**

- [x] Existing work is committed or backed up (docs commit `589f9c9`, pushed)
- [x] No secrets, model weights, cache media, or local databases staged
- [x] `git status` clean after the baseline commit
- [x] Dependency/tool inventory recorded (above and in AGENTS.md)

**Deferred:** none for this sprint.

**Open item for Sprint 1:** AMD GPU means the runtime feasibility spike must
validate llama.cpp **Vulkan** (RX 6400 is RDNA2; ROCm on Windows is not a practical
option for this card) or CPU inference as fallback.

## 2026-10-30 — Sprint 1: Hardware and runtime feasibility spike

**Goal:** Prove a small local vision model accepts image input on the target
machine before building around it.

**Plan & scope:** validate a Windows-friendly runtime + small VLM on the RX 6400
(4 GB, AMD — no CUDA); single-image and multi-image tests with deterministic
ground-truth frames; measure latency/token cost; record decision. Deferred:
real-video quality evaluation (Sprint 11), context/KV tuning (Sprint 9).

**What was done:**

- Discovered existing local runtime: Ollama 0.40.11 with 19 models including a VLM
  (`qwen2.5vl:3b`) — avoided a multi-GB download entirely.
- Confirmed RX 6400 is not ROCm-supported (`gfx1034`) but Ollama's Vulkan backend
  runs it; server logs show the CLIP vision encoder on the Vulkan GPU device.
- Built deterministic ground-truth test frames (`scripts/make_test_image.ps1`,
  variant A: "HELLO 42"/red circle/green rectangle; variant B: "SECOND 77"/orange
  circle/purple rectangle) and a reproducible correctness gate
  (`scripts/vlm_smoke_test.py`, stdlib-only) plus a timing probe
  (`scripts/vlm_timing_probe.py`).
- Benchmarked two candidate models with uncached vision encoding.

**Results (see `docs/runtime-feasibility.md` for full numbers):**

- `qwen2.5vl:3b`: image input + ordering correct, but ~1060 vision tokens/image and
  20–40 s encode per image → ~6 min for a 12-frame request. Too slow for live use.
- **`qwen3.5:4b` (chosen): ~327 tokens/image, ~2.4 s encode/image, 2-image ordering
  correct, 75% GPU. 12-frame request extrapolates to ~30–45 s.** Follow-ups on
  cached frames are seconds.
- Notable finding: `think:false` made the model skip one of three answer parts
  (fast but lossy); the correctness gate runs with thinking on.

**Verification (roadmap Sprint 1 checklist):** all six boxes pass — see
`docs/runtime-feasibility.md`. Smoke tests: single PASS, multi PASS.

**Files changed:** `scripts/make_test_image.ps1`, `scripts/vlm_smoke_test.py`,
`scripts/vlm_timing_probe.py` (new); `docs/runtime-feasibility.md` (new);
`.env.example` (runtime URL/model updated to Sprint 1 decision);
`docs/dev-log.md` (this entry).

**Tests run:** `vlm_smoke_test.py` single (PASS) and multi (PASS) on both models;
timing probes ×5; text-only prompt-eval isolation probe.

**Unverified / deferred:** peak-VRAM measured indirectly (GPU split %), not with a
perf counter; real-video frame quality; `num_ctx` 8192 behavior under load;
`qwen3-vl:2b` comparison. All assigned to Sprints 9/11.

**Deviation note:** inference default port becomes Ollama's `11434` (not the
architecture doc's `8081` example). Intent (separate configurable ports) preserved;
architecture.md to be updated when the Sprint 9 adapter lands.

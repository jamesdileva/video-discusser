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

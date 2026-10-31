# AGENTS.md — Working Conventions for Video Discusser

Instructions for AI agents and human contributors working in this repository.

## Project overview

Video Discusser is a **local-first** Windows desktop application for discussing video
evidence and events. A browser userscript syncs the current YouTube video URL and
pause timestamp to a local FastAPI backend; the backend extracts a bounded set of
timestamped frames with FFmpeg and asks a local vision-language model (VLM) for a
grounded answer. A static HTML dashboard shows sync state, evidence, and the
conversation.

Key facts that shape every decision:

- Single user, single machine. No cloud AI APIs, no accounts, no telemetry.
- Target hardware: Windows 11, **AMD Radeon RX 6400 (4 GB VRAM)**, 16 GB RAM.
  This is an AMD GPU — there is **no CUDA**. The local VLM runtime path is
  llama.cpp (Vulkan or CPU), not vLLM. vLLM does not support native Windows.
- Every resource (frames, context, concurrency, timeouts) is bounded and configurable.
- Output is **commentary, not legal advice**. Observations must be separated from
  inference; uncertainty must be stated.

## Authoritative documents

Read these before making changes. They are the source of truth — do not contradict
them in code without updating them first.

| Document | Role |
|---|---|
| `docs/architecture.md` | Design, API contract, domain models, security baseline |
| `docs/sprint-roadmap.md` | Sprint sequence, tasks, verification gates, definition of done |
| `docs/implementation-guide.md` | Step-by-step implementation and debugging companion |
| `docs/new-idea.md` | Deferred proposal: whole-video summary mode (do not implement until the core pipeline works and the roadmap is updated) |
| `docs/dev-log.md` | Append-only log: per-sprint records of plan, changes, tests, results |

Where a sprint task conflicts with the roadmap's letter, the roadmap's *intent*
(vertical slice, verified gates, bounded resources) wins; record the deviation in
`docs/dev-log.md`.

## Environment (verified 2026-10-30)

- Windows 11 x64, Git Bash shell
- Python 3.14.3 (`python`; the `py` launcher has no 3.12 — target the installed 3.14)
- FFmpeg N-124616 on PATH (`ffmpeg`, `ffprobe`)
- yt-dlp: **not installed** (optional dependency; app must run without it)
- GPU: AMD Radeon RX 6400, 4 GB VRAM; system RAM 15.9 GB
- gh CLI 2.98.0 authenticated as `jamesdileva`; remote `origin` = `github.com/jamesdileva/video-discusser` (public)

## Commands

```bash
# Environment (first time)
python -m venv .venv
source .venv/Scripts/activate        # Git Bash; PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

# Run the backend (never on the inference port)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Tests (must pass with no GPU, no network, no model runtime)
pytest
pytest tests/test_sync.py -q         # narrow test during development

# Environment self-check
python scripts/check_environment.py
```

Configuration lives in `.env` (copy from `.env.example`, never commit). Backend
default port **8000**, inference runtime default port **11434** (Ollama; the
llama-server fallback uses 8081) — always different.

## Sprint workflow

Every sprint follows the same loop, recorded in `docs/dev-log.md`:

1. **Plan** — State the sprint goal in one sentence and the exact files involved.
2. **Scope** — List the tasks and the verification checklist from
   `docs/sprint-roadmap.md`; note anything explicitly deferred. Small and coherent
   beats broad and speculative.
3. **Implement** — Smallest coherent change that satisfies the scope. Follow the
   existing layout in `docs/architecture.md` §5. Match surrounding code style.
4. **Verify** — Run the narrow tests, then the full suite (`pytest`), then the
   sprint's manual checks. Record what passed, what failed, and what remains
   unverified. Do not mark work complete because the code exists.
5. **Commit + push** — One commit (or a small series) per sprint with a message
   naming the sprint, e.g. `Sprint 2: project skeleton, config, health endpoint`.
   Push to `origin/main` after verification passes.

Cross-sprint definition of done (from the roadmap): repository runnable and tested,
relevant automated tests green, manual checks executed, results recorded, docs
updated when a decision changed, earlier acceptance criteria still passing.

## Code conventions

- Python 3.14, fully type-annotated public functions; Pydantic models for every
  API request/response — no loose dicts across layer boundaries.
- FastAPI app factory in `app/main.py`; routers, services, adapters, schemas as laid
  out in `docs/architecture.md` §5. Services are independent of HTTP.
- Configuration via `app/config.py` (Pydantic Settings). Nothing hard-codes ports,
  paths, frame budgets, or model names. A configuration validator enforces hard
  upper bounds even when a request asks for more.
- Subprocesses (FFmpeg, yt-dlp): argument arrays only — never shell string
  interpolation, never `shell=True` with untrusted values. Always set timeouts,
  capture bounded stderr, check return codes, verify output files.
- All state changes go through services (e.g. `ActiveVideoService` with revision
  counters), never through bare module-level mutable dicts.
- Frontend is static HTML/CSS/vanilla JS. Render all dynamic text with
  `textContent`; never inject model output as HTML.
- Errors: structured error codes (`400 no_active_video`, `503 inference_unavailable`,
  …) per `docs/architecture.md` §7. Never show raw stack traces to the browser.
- Logging: structured, includes `request_id` and stage; never logs full prompts,
  user questions, or full URLs by default.

## Testing discipline

- `pytest` must pass with **no GPU, no model runtime, no network**. External
  dependencies (media source, inference runtime) are always faked behind adapters
  in tests.
- Every API boundary gets a test; every fix gets a regression test first.
- Tests live in `tests/`, named after the module or route they cover.
- GPU/model evaluation happens only in explicitly marked manual/integration sprints
  (e.g. Sprint 1, Sprint 11) and its results are recorded in `docs/dev-log.md`.

## Security & privacy rules (non-negotiable)

- Bind backend and inference runtime to `127.0.0.1`, never `0.0.0.0`.
- CORS: exact dashboard origin allowlist — never `*`. Validate `Host`/`Origin`.
- Treat everything from the browser (sync payloads, URLs, frame IDs) as untrusted
  input. Validate, bound, and reject.
- Never send prompts, frames, URLs, or video content to any cloud service.
- Frame/preview routes serve only validated, application-owned files inside the
  configured cache root; reject path traversal.
- Keep `.env`, `.venv/`, `data/cache/`, `data/sessions/`, model weights
  (`*.gguf`), and logs out of Git.
- Do not bypass platform access restrictions or DRM; unsupported sources fail
  with clear errors.
- Legal framing: the app never presents output as legal advice or a definitive
  finding. This limitation is never removed from prompts or UI.

## Git conventions

- Branch: commit verified sprint work to `main` (solo project); revert rather than
  force-push if a pushed change breaks verification.
- Commit messages: `Sprint N: short summary` or `Sprint N: fix scope` style;
  present tense, no noise commits.
- Never commit secrets, model weights, cached media, or local databases.

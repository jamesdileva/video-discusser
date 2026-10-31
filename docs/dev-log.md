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

## 2026-10-30 — Sprint 2: Project skeleton and configuration

**Goal:** Small, testable FastAPI application with configuration centralized.

**Plan & scope:** app package per architecture.md §5; pinned dependencies;
validated settings with hard bounds; `GET /api/health`; static dashboard shell;
request-ID + structured logging foundations; initial test suite. Deferred:
sync/status routes (Sprint 3), request-ID *in every log line* for jobs (arrives
with orchestration), environment check script (Sprint 6).

**What was done:**

- Python 3.14 compatibility confirmed: FastAPI 0.162.0, Pydantic 2.14.2,
  uvicorn 0.54.0, httpx 0.28.1, pytest 9.2.0 all install and run clean on 3.14.3.
- `pyproject.toml` — exact-pinned runtime + dev deps, pytest config.
- `app/config.py` — `Settings` (pydantic-settings, `.env` loading) with hard
  bounds on every budget, loopback enforcement for `APP_HOST` and the inference
  URL, port-collision rejection, empty-model rejection, and an actionable
  `ensure_cache_dir()` startup check.
- `app/main.py` — app factory (`create_app(settings)` for test injection),
  lifespan that validates/creates the cache dir and logs a redacted startup
  summary, request-ID middleware (context var + `X-Request-ID` header), logging
  setup (request line only at DEBUG).
- `app/api/health.py` + `app/schemas/status.py` — health contract; status
  schema defined for Sprint 3.
- `app/static/` — minimal dashboard shell that polls `/api/health` and renders
  with `textContent` only.
- `tests/` — 24 tests: health contract, request-ID echo/assignment, dashboard
  serving, config defaults, loopback/port/bounds rejection matrix, cache-dir
  behavior. All settings fixtures isolated from the local `.env`.

**Verification (roadmap Sprint 2 checklist):**

- [x] `GET /api/health` returns 200 and version (live curl: `{"status":"ok","version":"0.1.0"}`)
- [x] Invalid configuration fails with a clear message (`APP_HOST=0.0.0.0` →
  "must be a loopback address…"; port collision → "must differ from APP_PORT")
- [x] Backend listens on `127.0.0.1:8000` (live uvicorn run)
- [x] Runtime URL defaults to a different port (11434), collision rejected
- [x] `pytest` runs without GPU or network (24 passed, 0.18s)
- [x] Logs do not include user questions or full URLs by default (app logger
  emits lifecycle INFO + DEBUG request lines only; API design keeps sensitive
  payloads in POST bodies. Note: uvicorn's own access log prints request paths
  — acceptable because paths carry only opaque IDs by design.)

**Files changed:** `pyproject.toml`; `app/` package (`__init__`, `config`,
`main`, `api/health`, `schemas/status`, `static/` shell); `tests/` (`conftest`,
`test_health`, `test_config`); `README.md` status; `docs/dev-log.md` (this entry).

**Tests run:** `pytest` — 24 passed. Live: health curl, dashboard curl,
bad-config startups (2 rejection cases).

**Unverified / deferred:** `X-Request-ID` correlation across multi-stage jobs
(Sprint 10+); settings hot-reload (not planned); `scripts/check_environment.py`
(Sprint 6).

**Environment note:** deprecation warning observed — starlette's TestClient
hints that `httpx` is deprecated in favor of `httpx2` upstream. No action now;
revisit when the inference adapter (Sprint 9) picks its HTTP client.

## 2026-10-30 — Sprint 3: Sync schema and active-video service

**Goal:** Make video state valid, testable, and race-aware.

**Plan & scope:** `SyncPayload`/`ActiveVideoState` schemas; strict YouTube URL
classification; thread-safe `ActiveVideoService` with immutable revisioned
snapshots; `POST /api/sync` + `GET /api/status`; structured error envelope with
stable codes. Deferred: inference runtime probe (`unknown` until Sprint 9),
request-size middleware (Sprint 13), local-file source (Sprint 6).

**What was done:**

- `app/schemas/sync.py` — `SyncPayload` (URL ≤2048 chars, finite non-negative
  timestamp via `allow_inf_nan=False`, optional `video_id` pattern-checked,
  `sync_source` literal) and frozen `ActiveVideoState` (architecture §6 fields).
- `app/services/youtube_url.py` — parse-only classification: allowlisted hosts
  (`youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`), http(s)
  only; `watch?v=` with exactly one valid `v`, `youtu.be/<id>` (single-slash
  strict), `shorts/<id>`; everything else → `invalid_url` / `missing_video_id`.
  Host-suffix lookalikes (`youtube.com.evil.com`) fail exact-match.
- `app/services/active_video.py` — lock-guarded service, frozen snapshots,
  revision increments on every accepted sync (stale syncs never overwrite
  silently); concurrency test drives 40 syncs across 8 threads → revisions 1–40
  unique.
- `app/api/sync.py`, `app/api/status.py`, `app/api/deps.py`, `app/api/errors.py`
  — routes translate `YouTubeUrlError` to 422 codes; `video_id` mismatch → 422
  `video_id_mismatch`; `RequestValidationError` → envelope `validation_error`
  with field list (no body echo); unhandled → generic 500 `internal_error`,
  stack logged server-side only.
- Status reports services separately: backend `ready`, inference `unknown`
  (probe arrives Sprint 9), media_tools via `shutil.which("ffmpeg")`.
- Logs: `sync accepted revision=… video_id=… timestamp=… source=…` — full URLs
  never logged (verified by grep on the live server log).
- Docs: AGENTS.md inference-port line corrected to 11434 (Sprint 1 decision).

**Verification (roadmap Sprint 3 checklist):**

- [x] Valid URL/timestamp updates state (live curl: revision 1, full snapshot)
- [x] Invalid URL and timestamp return 4xx (live: `invalid_url`, NaN → `validation_error`)
- [x] Re-sync increments revision (unit + live)
- [x] Status returns `null` state before first sync (unit test)
- [x] URL parsing works with extra query parameters (parametrized tests)
- [x] A stale request cannot silently overwrite a newer snapshot without
  incrementing revision (dedicated test: stale sync → revision bumps, snapshot moves)

**Tests run:** `pytest` — 64 passed (24 prior + 40 new). Live: valid sync,
status before/after, invalid host, NaN timestamp, URL-leak log grep.

**Fix during sprint:** `youtu.be//<id>` (double slash) initially parsed via
`lstrip` — tightened to single-slash strip; regression test added
(`test_rejected_url_forms`).

**Unverified / deferred:** userscript round-trip (Sprint 5); `manual` sync
endpoint variant; CORS/Origin hardening (Sprint 13).

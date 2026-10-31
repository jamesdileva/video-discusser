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

## 2026-10-30 — Sprint 4: Dashboard shell and service status

**Goal:** First usable local dashboard before adding inference.

**Plan & scope:** rewrite `app/static/{index.html,styles.css,app.js}` into a
live status dashboard — `/api/status` polling (2.5 s, paused on hidden tabs),
per-service indicators, active-video display, empty/offline/stale states,
chat shell with disabled-until-synced input, textContent-only rendering.
Deferred: model answers (Sprint 10), server-sent events (post-MVP), frame
previews (Sprint 8), sessions persistence (Sprint 15).

**What was done:**

- `index.html` — services card (dots + labels + version), active-video card
  with empty state and key/value details, discussion card with bounded chat
  log and a form whose input starts disabled.
- `app.js` — single-flight polling loop via `setTimeout` (no overlapping
  requests), immediate poll on `visibilitychange`, offline banner that keeps
  last-known values visibly stale ("last ok: HH:MM:SS"), service state → dot
  class mapping, `m:ss.t` timestamp formatting, chat log capped at 50
  messages. Every dynamic write goes through a `setText` helper using
  `textContent`.
- `styles.css` — dark theme, state-colored dots, responsive single-column
  layout, disabled affordances.
- `tests/test_dashboard.py` — served HTML contains all IDs the JS requires;
  static guard that `app.js` contains no HTML-injection sink (`innerHTML`,
  `outerHTML`, `insertAdjacentHTML`, `document.write`) and does contain the
  visibility-pause wiring.

**Verification (roadmap Sprint 4 checklist) — performed in a real browser
(ZCode in-app browser, DOM snapshots + screenshots + evaluate):**

- [x] Dashboard loads without JavaScript errors — all features functional
  (rendering, polling cycle, chat submit, offline recovery after backend restart).
- [x] No synced video displays a clear empty state (verified in browser).
- [x] Posting a test sync updates the dashboard — curl `POST /api/sync`
  appeared on the next poll (~2.5 s): video ID, `02:05.4 (125.4s)`, revision #1,
  input/button enabled.
- [x] Backend shutdown shows disconnected state — banner visible, backend dot
  `unavailable`, last-known video details remain on screen as stale.
- [x] User/model text is rendered as text, not HTML — hostile input
  `<img src=x onerror=alert(1)>` displayed verbatim; `querySelectorAll("img")`
  count in the chat log: 0.
- [x] Layout usable at common desktop window sizes — screenshots at 1280×800
  and 700×640; no overflow, readable, keyboard-focusable input.

**Notes:**

- The full-page screenshot mode of the test browser produced a tiling
  artifact (2×2 duplication); plain viewport screenshots confirmed correct
  rendering. Not a page bug (DOM state was verified independently).
- Backend restart clears in-memory active-video state by design; the
  dashboard correctly returned to the empty state. Persistence is a later,
  opt-in sprint (roadmap Sprint 15).

**Tests run:** `pytest` — 68 passed (64 prior + 4 new static contract tests);
browser verification as above.

**Unverified / deferred:** pause-on-hidden-tab behavior observed via
`visibilitychange` wiring only (static test), not with a manually hidden tab;
userscript round-trip (Sprint 5).

## 2026-10-30 — Sprint 5: YouTube userscript synchronization

**Goal:** Make the real pause-to-sync workflow reliable.

**Plan & scope:** `browser/youtube-sync.user.js` (Tampermonkey), SPA-safe
pause capture, dedupe, manual sync fallback, status pill, `browser/README.md`
setup + manual checklist, dev-only fixture routes + local test harness,
Node-run core tests. Deferred: real-Tampermonkey manual run (user machine —
checklist provided), ad filtering beyond best-effort, non-watch pages,
settings UI beyond the menu command.

**What was done:**

- `browser/youtube-sync.user.js` — `@match` limited to youtube.com watch
  pages; capture-mode `document`-level `pause` listener (survives video
  element replacement, no rebinding); `location.href`/`currentTime` read at
  event time; `yt-navigate-finish` resets the badge on SPA navigation;
  duplicate suppression (same video+source within ±0.25 s); manual **Sync
  now** (pill button + `GM_registerMenuCommand`, `sync_source: "manual"`);
  loopback-validated "Set backend origin" menu command; transport via
  `GM_xmlhttpRequest` (`@connect 127.0.0.1/localhost`) so the backend needs
  no CORS headers; best-effort ad-break filter; textContent-only pill.
  DOM-free core (`extractVideoId/buildPayload/isDuplicate/formatTimestamp`)
  exported for tests and kept mirroring `app/services/youtube_url.py`.
- Dev harness: `app/static/dev-harness.html` loads the real userscript with
  GM stubs (proxied to same-origin fetch), a committed 27 KB fixture clip
  (`browser/fixtures/test-clip.mp4`), synthetic pause, simulated SPA
  navigation via the documented `__vdTestHref` seam (a page could spoof the
  reported URL, but it already controls its own video element — no new
  capability), and an activity log. Served through dev-only routes
  (`/dev/youtube-sync.user.js`, `/dev/test-clip.mp4`) registered only when
  `APP_ENV=development`.
- `tests/js/userscript_core.test.cjs` + `tests/test_userscript.py` — Node
  assertion suite for the core (URL cases mirror the backend pytest matrix so
  client/server cannot drift), pytest wrapper (skips if node absent), static
  metadata/safety checks, dev-route contract.

**Bugs caught by verification during this sprint:**

1. `setBadge` referenced a badge const scoped inside `ensureBadge()` →
   ReferenceError swallowed into "sync failed". Fixed by hoisting badge refs
   to the `main()` scope. (Caught by the first harness run.)
2. Harness-only: SPA-simulation IDs were 12 chars → correctly rejected by the
   11-char regex ("not a watch page"). Fixed the fixture.
3. Client/server drift caught by the Node suite: `extractVideoId` accepted
   non-http(s) schemes (`ftp://www.youtube.com/...`) that the backend
   rejects; scheme check added so the client never sends doomed requests.

**Verification — Node suite + live harness run (real browser, real backend):**

- [x] Pause sends the correct URL and timestamp (synthetic pause at 4.2 s →
  POST with `video_id`, `timestamp_seconds: 4.2`, `pause_event`; badge
  "synced 00:04.2"; server state confirmed via `/api/status`).
- [x] Play/resume/pause cycles update state — a natural pause during playback
  after an earlier sync produced a second, distinct sync attempt.
- [x] Navigating to another video in the same tab (simulated SPA) syncs the
  new video ID without reload (`aaaaaaaaaa7` @ 2.5 s).
- [x] Pausing near 0 seconds is valid — ≥ 0 enforced; near-zero pauses within
  the epsilon dedupe as duplicates by design (covered by Node boundary tests).
- [x] Backend offline does not break playback — pause showed "backend
  offline", video played on, and manual **Sync now** after restart succeeded
  (`sync_source: "manual"`, server rev 1 on the fresh process).
- [x] Other websites are not targeted — `@match` youtube.com watch pages only
  (static test), core host allowlist mirrors the backend.

Also: duplicate pause suppressed with no new request; "Sync now" works;
backend rejection codes surface in the pill.

**Tests run:** `pytest` — 74 passed (68 prior + 6 new); node core suite —
all assertions passed (including after the scheme fix).

**Still unverified (needs your machine — see `browser/README.md` checklist):**
the real Tampermonkey round-trip on live YouTube (install, @connect approval,
SPA navigation, real playback controls). Everything up to Tampermonkey itself
is verified by the harness.

**Fixture note:** `browser/fixtures/test-clip.mp4` is a committed 27 KB
generated test clip (testsrc pattern) — deliberate test fixture, not cached
media.

## 2026-10-30 — Sprint 6: Media-source adapter and environment checks

**Goal:** Isolate source access and make extraction failures understandable.

**Plan & scope:** `MediaSource` contract + registry; local-file source first
(allowlisted roots from trusted config); opt-in yt-dlp YouTube adapter; single
disciplined subprocess chokepoint; `scripts/check_environment.py`. Deferred:
frame extraction (Sprint 7), real yt-dlp download (not installed here — runner
faked at the seam; the adapter is exercised for real once the feature is
used), status-endpoint granularity.

**What was done:**

- `app/adapters/subprocess_utils.py` — the only path to external tools:
  argument arrays (non-list input rejected), explicit timeout (subprocess.run
  kills and reaps the child), bounded stderr tails, explicit return-code
  checks, typed `CommandError` with stable codes (`media_tool_missing`,
  `process_timeout`, `process_failed`).
- `app/adapters/media_source.py` — `MediaRequest`/`ResolvedMedia` frozen
  dataclasses, `MediaSource` protocol, `MediaSourceRegistry` (on
  `app.state.media_sources`), shared `probe_media()` via ffprobe JSON
  (actionable errors: missing tool, non-video file, non-numeric/non-positive
  duration).
- `app/adapters/local_file_source.py` — resolves only paths inside
  `LOCAL_MEDIA_DIRS` roots (resolved-path containment, so `..` traversal and
  symlink escapes fail as `local_path_not_allowed`); disabled with guidance
  when no roots are configured; probes before returning.
- `app/adapters/youtube_source.py` — opt-in via `YOUTUBE_SOURCE_ENABLED`
  (downloading must comply with platform terms; no DRM circumvention);
  validates the URL with the sync URL parser *before* any tool is invoked;
  clear `media_tool_missing` when yt-dlp is absent; generated UUID output
  names (never URL-derived); typed failures (`media_download_failed`,
  `media_download_timeout`); `cleanup_after_use=True` for downloads.
- `app/config.py` — `LOCAL_MEDIA_DIRS` (semicolon-separated; commas unusable
  inside Windows drive letters), `YOUTUBE_SOURCE_ENABLED`,
  `MEDIA_DOWNLOAD_TIMEOUT_SECONDS`.
- `app/main.py` — registry wired into app state.
- `scripts/check_environment.py` — Python/config/FFmpeg/ffprobe required;
  yt-dlp + inference runtime optional warnings; cache writability; local
  roots; exit 0/1 semantics.

**Verification (roadmap Sprint 6 checklist):**

- [x] Local sample video probed and read by FFmpeg — the committed fixture
  clip resolves: duration ≈ 10 s, 256×144, real ffprobe JSON (also through
  the app-wired registry).
- [x] Unsupported URLs rejected before invoking external tools — spy runner
  asserts zero invocations for non-YouTube URLs and while disabled.
- [x] Missing FFmpeg produces an actionable error — `media_tool_missing`
  includes install guidance (`winget install Gyan.FFmpeg`).
- [x] yt-dlp failure does not crash — every failure surfaces as typed
  `MediaSourceError` with bounded stderr in the message.
- [x] Child processes time out and terminate correctly — 30 s sleeper with a
  2 s budget raises `process_timeout` in < 10 s wall time (run() reaps).
- [x] No command built by string concatenation — argument arrays enforced in
  `run_command` (type check) and asserted by every fake runner; URL rides as
  a single argv element.

Also: config parsing tests (semicolon split), env script failure path
(`APP_HOST=0.0.0.0` → exit 1 + "Configuration invalid").

**Tests run:** `pytest` — 102 passed (74 prior + 28 new). Live:
`check_environment.py` → `Result: OK` exit 0 (Ollama detected at 11434).

**Test bugs caught during the sprint (mine, fixed immediately):** a
monkeypatch of the shared `shutil` module that leaked into ffprobe lookups
(fixture now delegates non-yt-dlp lookups), and a stderr test whose command
never exited non-zero.

**Unverified / deferred:** a real yt-dlp download against YouTube (needs the
binary + network + terms compliance decisions); frame extraction consumes
these adapters in Sprint 7.

## 2026-10-30 — Sprint 7: Frame extraction and bounded sampling

**Goal:** Produce timestamped, inspectable frames within a strict resource
budget.

**Plan & scope:** pure sampling module (window clamping, anchor-inclusive
even spread, configured-cap clamp), `extract_frames` with per-frame
verification (existence, non-empty, probed dimensions, SHA-256), generated
frame IDs, cache keys over source identity + plan + settings, disk-backed
`FrameStore` re-indexed at startup, safe `GET /api/frames/{frame_id}`, and an
age-bounded stale sweep. Deferred: dashboard thumbnails (Sprint 8 — the
roadmap's own UI sprint; see deviation note), job queue/concurrency limits
(Sprint 12).

**What was done:**

- `app/services/frame_sampling.py` — `compute_analysis_window` (start clamps
  to 0 and to `duration - 0.05`), `plan_frame_timestamps` (anchor always
  included as the last timestamp, remaining samples evenly spread, dedupe on
  rounding — the cap is a maximum, never a promise), `clamp_max_frames`
  (configured cap wins over any user request).
- `app/services/frame_extraction.py` — one FFmpeg invocation per timestamp
  (`-ss` fast-seek, scale filter preserving aspect, `-q:v` mapped from
  configured JPEG quality); every output verified (exists, non-empty,
  ffprobe dimensions — the scale filter's arithmetic is never assumed);
  `FrameRecord` metadata (generated 32-hex ID, actual timestamp, relative
  path, dims, SHA-256, source revision); batch metadata JSON per cache key;
  `FrameStore` (thread-safe index, `load_from_disk`, containment-checked
  `resolve_path`, stale sweep that never touches young entries).
- `app/api/frames.py` — `GET /api/frames/{frame_id}`: 32-hex ID format gate,
  registry lookup, containment-checked path, structured 404 envelope.
- `app/main.py` — store constructed before the app, re-indexed in lifespan.

**Real-world finding (fixed with a design change, not a patch):** the
fixture's last *decodable* frame is at 9.9 s while the container duration is
10.0 s — a seek to 9.95 s produces no output and this FFmpeg build exits -22.
Extraction now retries each timestamp pulled back in bounded steps
(0.25 s, 0.5 s, clamped to the window and to the previous recorded timestamp
so monotonicity holds) and records the timestamp that actually produced the
frame. The EOF guard in the sampler stays as the first line of defense.

**Verification (roadmap Sprint 7 checklist):**

- [x] A 180-second window stays within the configured frame cap (plan ≤ 12;
  `clamp_max_frames(999, 12) == 12`).
- [x] A timestamp before 180 seconds produces a start time of zero.
- [x] Frame timestamps are monotonic and within the requested window (even
  after EOF pull-backs — retry candidates are clamped to the previous frame).
- [x] Empty/corrupt extraction returns a clear error (`frame_extraction_failed`
  with FFmpeg stderr tail).
- [x] Traversal attempts and unknown frame IDs are rejected — verified at all
  three layers: literal `../..` is normalized by the HTTP client, encoded
  `%2F` never matches the router, and the handler enforces 32-hex + registry
  + containment (unit-tested with an injected escaping record).
- [x] Preview images display — served frame rendered in a real browser
  (screenshot, `image/jpeg` 200).
- [x] Cache keys change when sampling settings change (dimension/quality/
  timestamps/source identity each alter the key; identical inputs are
  deterministic) and cache hits perform zero subprocess calls.

**Tests run:** `pytest` — 134 passed (102 prior + 32 new; extraction/API
tests use real FFmpeg and skip on machines without it). Live: extraction of
4 frames from the fixture (anchor honestly recorded at 9.7 s after pull-back),
`curl` 200 `image/jpeg`, bad ID → envelope, browser render.

**Deviation note:** the roadmap's Sprint 7 checklist includes "preview images
display in the dashboard"; dashboard thumbnails belong to Sprint 8 (evidence
preview UI) per the same roadmap. The endpoint-level render was verified
instead; no architecture change implied.

**Unverified / deferred:** extraction from a YouTube download end-to-end
(needs yt-dlp); cache budget by total disk size (Sprint 12); `fps`-style
dense sampling near events (post-MVP Sprint 19).

## 2026-10-31 — Sprint 8: Evidence preview and question workflow UI

**Goal:** Let the user inspect what the model will actually see.

**Plan & scope:** close the loop on this machine — `POST /api/sync/local-file`
(the trusted-UI half of Sprint 6's local-file design, allowlist-gated),
`POST /api/evidence/preview` (resolve → plan → extract, no model), and the
dashboard evidence card (window selector, thumbnails with clickable
timestamps, stage/error states, stale-snapshot marker). Deferred: inference
stage (Sprints 9–10), full job queue (Sprint 12 — a 409-busy lock now),
frame-max selector (server clamp covers it).

**What was done:**

- `app/api/sync.py` — `POST /api/sync/local-file`: resolves through the
  local-file source (allowlist + probe), generates a `local_<sha12>` video
  ID, syncs with `source="local_file"` (`ActiveVideoService.apply_sync`
  extended with `source`/`title`); logs never include the path.
- `app/api/evidence.py` — `POST /api/evidence/preview`: snapshot tagged with
  its revision; request window/frames clamped to configured bounds (schema
  ceilings are sanity-only; config is the effective bound); single-flight
  lock → structured 409 `extraction_in_progress`; `MediaSourceError` /
  `FrameExtractionError` mapped to stable codes and HTTP statuses
  (422 user-input, 503 service-side, 502/504 download, 500 extraction).
- Dashboard — evidence card: bounded window selector (30/60/180 s, at or
  below the server default), Preview button (disabled until a video exists
  and while in flight), stage line, analysis-window line, thumbnail strip
  (`img.src` attribute + textContent captions; YouTube timestamps link out
  at `?t=<floor>s`, local files show plain labels), warnings line, stale
  marker ("belongs to an earlier snapshot"), and the sampling-gap note.
  Local-file sync row in the Active video card.
- `app/main.py` — `NoCacheStaticFiles` (stale `app.js` against fresh HTML
  produced a broken UI during verification) + cache-busting script version.

**Bugs found and fixed during this sprint's verification:**

1. **Env-source parsing bug** (would break every real `.env` deploy):
   pydantic-settings JSON-decodes `list[Path]` fields from the environment
   *before* field validators run, so `LOCAL_MEDIA_DIRS=C:\Videos;D:\Clips`
   crashed at startup. Fixed with `Annotated[list[Path], NoDecode]`; two
   regression tests now exercise the env source directly (kwargs injection
   had masked the path — the exact gap unit tests are for).
2. **Stale-JS caching**: the IAB served a cached `app.js` against fresh HTML,
   silently disabling new features. Fixed with `Cache-Control: no-cache` on
   static files plus a versioned script URL.
3. **Floating-point label bug**: `9.7 - 9` floors to tenths digit 6, so
   "00:09.7" displayed as "00:09.6". `formatTimestamp` now formats from the
   decimal string (`toFixed(1)`); fixed in the dashboard and the userscript
   core (Node tests updated for the deterministic half-way case).

**Verification (roadmap Sprint 8 checklist) — real browser, real backend:**

- [x] Frame timestamps visible before model analysis — captions + window
  line render; anchor honestly shows 00:09.7 after the EOF pull-back.
- [x] Duplicate submissions prevented — button disabled while in flight;
  server 409 `extraction_in_progress` unit-tested by holding the lock.
- [x] A failed extraction does not leave the UI permanently loading — YouTube
  preview (source disabled) shows an actionable error, button re-enables, old
  frames stay visible.
- [x] A changed video is visually distinguishable — after re-syncing,
  "This preview belongs to an earlier snapshot (#1/#2) — the active video has
  changed." appears and clears on the next preview.
- [x] The UI clearly identifies the active analysis window —
  "Analysis window: 00:00.0 → 00:09.9 (12 frames, snapshot #2)".
- Frame thumbnails verified visually by screenshot (the in-app browser's
  `img.complete` reports false while images visibly render — quirk noted;
  direct fetch of each URL is 200 `image/jpeg`).

**Tests run:** `pytest` — 148 passed (134 prior + 14 new). Node core suite
green. Live: local-file sync via UI, preview via UI, stale marker ×2, failure
path, cache-key stability across identical previews.

**Unverified / deferred:** preview of a real YouTube download (needs yt-dlp +
opt-in); question submit still a local placeholder until Sprint 10; UI
polish pass comes with Sprint 14 (trust/layout).

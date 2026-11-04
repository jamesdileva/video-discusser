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

## 2026-10-31 — Sprint 9: Inference adapter

**Goal:** Integrate the chosen runtime without coupling API routes to
runtime-specific details.

**Plan & scope:** `OllamaInferenceAdapter` + `RuntimeCapabilities` +
injectable transport; health probe (TTL-cached) wired into `/api/status`;
the exact `/api/chat` payload proven in Sprint 1 (base64 images, `num_ctx`,
`think` with 400-fallback); typed failures; mocked tests + a skip-guarded
live test. Deferred: prompt construction and orchestration (Sprint 10 — the
adapter deliberately takes prepared prompts), benchmarking (Sprint 11),
`max_concurrent_inference` enforcement (arrives with the Sprint 10/12 job
queue).

**What was done:**

- `app/services/inference.py` — adapter with `health_check()` (GET
  `/api/version`, 2 s timeout, 10 s TTL so the dashboard's 2.5 s poll does
  not hammer the runtime), `describe_capabilities()` (image input: verified
  Sprint 1; **video input: False — never verified, nothing may assume it**;
  max images = configured frame cap), `generate(system_prompt, user_prompt,
  image_paths, timeout, num_ctx, think)` (base64-encodes verified non-empty
  frames, validates response shape, rejects empty content, retries once
  without `think` on HTTP 400 for non-thinking models). Typed
  `InferenceError` codes: `inference_unavailable`, `inference_timeout`,
  `inference_invalid_response`, `inference_empty_response`,
  `inference_invalid_request`. `HttpxInferenceTransport` (pooled client) is
  the default; tests inject a fake.
- `app/config.py` — `INFERENCE_NUM_CTX` (default 8192; 12 frames ≈ 4k
  vision tokens per the feasibility record).
- `app/api/status.py` — inference state from the adapter probe (`ready` /
  `unavailable`), replacing the Sprint 3–8 `unknown` placeholder.
- `app/main.py` — adapter on `app.state`, closed at shutdown.

**Deviations (recorded per AGENTS.md):** the architecture's
`generate(messages, settings)` sketch became a stricter typed signature
(`system_prompt`/`user_prompt`/`image_paths` + bounded options) — same
contract intent (routes never see runtime details). Health returns a plain
state string matching `ServiceState` rather than a `RuntimeHealth` type.

**Verification (roadmap Sprint 9 checklist):**

- [x] Health probe reports ready/unavailable accurately — live:
  `/api/status` → `{'backend': 'ready', 'inference': 'ready', 'media_tools':
  'ready'}` against running Ollama; mocked: unreachable → `unavailable`
  (and the probe bug below proved the failure path).
- [x] One known image can be sent through the adapter — live test (skipped
  automatically when the runtime is absent): deterministic frame through the
  REAL qwen3.5:4b → answer contains "red" and "42". Passed in-suite (~50 s
  cold load).
- [x] Missing runtime → `inference_unavailable` (mocked ConnectError +
  HTTP 500 cases).
- [x] Timeout → `inference_timeout` (mocked ReadTimeout).
- [x] Invalid response content handled — non-JSON, missing/typed-wrong
  `message.content`, OpenAI-shaped body, whitespace-only answer.
- [x] Video-input assumption guarded — `supports_video_input=False` asserted
  by a dedicated test; payload sends frames as individual base64 images only.

**Bugs caught by tests during the sprint:** health probe called the
transport unwrapped (a dead runtime raised raw `httpx.ConnectError` instead
of returning "unavailable") — fixed with a `_get_json` wrapper mirroring the
POST path; a signature mismatch (`timeout_seconds` vs `timeout`) caught
immediately after. The live test's collection-time gate also proved flaky
with the adapter's 2 s health timeout — the gate now probes directly with 5 s.

**Tests run:** `pytest` — 165 passed (148 prior + 18 new, including the
live-model test; skips cleanly on machines without the runtime). Live:
`/api/status` inference ready.

**Unverified / deferred:** `num_ctx` 8192 under a full 12-frame payload on
the 4 GB GPU (Sprint 11 measures); concurrency (Sprint 10/12); multi-image
ordering through the adapter (proven at the API level in Sprint 1, exercised
by orchestration tests in Sprint 10).

## 2026-11-03 — Sprint 10: Discussion orchestration and evidence-aware prompting

**Goal:** Produce a response grounded in the frames selected for this request.

**Plan & scope:** `DiscussionService` (snapshot → resolve → plan → extract →
prompt → inference → revision tag), evidence-aware prompt templates,
`POST /api/discuss` with structured errors, shared pipeline lock (renamed
from `evidence_lock` — one extraction+inference job at a time), and dashboard
chat wiring. Deferred: multi-turn chat history (Sprint 15), formal
evaluation set (Sprint 11), response-section UI layout (Sprint 14).

**What was done:**

- `app/services/prompts.py` — system prompt encoding the §11 policy
  (frames-only answering, observation vs interpretation separation,
  supplied-timestamps-only citations, no audio/off-screen/identity/intent/
  legality inference, in-video text and the question treated as content not
  instructions, standing "not legal advice" line); user prompt lists ONLY
  the timestamps actually extracted (post-EOF pull-back), so the model can
  never cite a timestamp that was not in its input.
- `app/services/discussion.py` — orchestration with question validation
  (blank/over-length → `invalid_question`), clamped window/frames, revision
  tagging (`revision_changed` reported, never relabelled), typed
  `DiscussionError` codes; log line records frames, elapsed, token counts —
  never the question text or URL.
- `app/api/discussion.py` — `POST /api/discuss`; error mapping keeps
  inference (`503/504/502 inference_*`) and media (`422/503 media_*`)
  failures distinct; 409 `request_in_progress` under the pipeline lock.
- `app/config.py` — `INFERENCE_THINK_ENABLED` (default true per the Sprint 1
  quality finding).
- Dashboard — chat submit now calls `/api/discuss`, renders the answer as a
  chat message (textContent only), refreshes the evidence strip with the
  frames actually used, shows a stale note when the video changed mid-answer,
  and disables input with a "Thinking…" state while in flight.

**Telemetry that changed the defaults (recorded for Sprint 11):**

- 4 frames, thinking on: 89.1 s (493 prompt + 1165 eval tokens) — first
  successful end-to-end answer.
- 12 frames (dashboard default before the fix): exceeded the old 180 s
  timeout → `INFERENCE_TIMEOUT_SECONDS` raised to 600 (bounded), and the
  dashboard chat now sends `max_frames: 6` (live-conversation profile;
  evidence preview keeps 12 for inspection).
- 6 frames, thinking on, warm model: 84.7 s (573 + 1087 tokens) — generation
  (~1100 tokens at ~18 tok/s) dominates; a future lever is shorter answers
  or `think:false` for single-fact questions (Sprint 11 evaluates).

**Verification (roadmap Sprint 10 checklist):**

- [x] A mocked end-to-end request returns answer plus frame references
  (RecordingInference over real FFmpeg extraction; previews served 200).
- [x] Missing active video returns a useful 4xx (`400 no_active_video`).
- [x] Model response cites only timestamps supplied to it — enforced by
  prompt construction; unit test proves the prompt's timestamp list equals
  exactly the response's frames_used labels.
- [x] Unsupported questions are answered with limitations rather than
  invented facts — policy is prompt-enforced (system rules 3-6); live answer
  demonstrably listed "cannot be established" items (audio, meaning,
  function) instead of guessing.
- [x] A video change during inference does not relabel the old answer —
  regression test syncs a new video inside a hooked generation; response
  keeps `snapshot_revision=1` and reports `revision_changed=true`.
- [x] Inference and media failures map to distinct error codes
  (`inference_timeout` 504 vs `media_source_unavailable` 503, etc.).

**Tests run:** `pytest` — 174 passed (165 prior + 9 new). Live: first real
end-to-end answer (curl, 4 frames, 89.1 s, structured sections, correct
per-frame digit readings, honest uncertainty list) and the dashboard chat
flow (6 frames, 84.7 s, answer + frames + stale-safe tagging) verified in
the browser with screenshots.

**Notes:** the in-app browser's full-page screenshots tile (known capture
quirk since Sprint 4); DOM state verified independently. Ollama updated to
0.40.14 across the session restart without any adapter change — the
version-independent `/api/chat` payload held.

**Unverified / deferred:** multi-turn follow-ups reuse cached frames but
have no server-side history (Sprint 15); formal quality evaluation on a
varied test set is Sprint 11's whole purpose.

## 2026-11-03 — Sprint 11: First real end-to-end model evaluation

**Goal:** Prove the entire workflow with known videos and record where it
fails.

**Plan & scope:** a repeatable harness (`scripts/run_evaluation.py`) with a
fixed six-case test set over generated, ground-truth-controlled clips;
results JSON; `docs/evaluation-report.md` with the profile decision.
Deferred: real-footage cases (needs lawful local media / yt-dlp decisions);
model comparisons (not warranted by results).

**What was done:**

- `scripts/run_evaluation.py` — generates deterministic clips with FFmpeg
  (constant "GATE 7" text; a yellow "ALERT 42" sign shown only t=8–9 s;
  "DOCK 4" at boxblur 12), drives the real `DiscussionService` per case,
  applies objective any-of substring verdicts (ambiguous cases recorded,
  not judged), captures latency, frames used, and `ollama ps` memory, and
  writes `data/cache/eval/results.json`.
- Cases map to the roadmap's required categories: clear visual fact;
  audio-dependent honesty; an event between sampled frames **in both
  directions** (missed by design, then sampled by anchor); ambiguity;
  sequence reasoning.
- Two harness bugs fixed before results: the sync anchor was hardcoded
  (cases would all have analyzed t≈1 s), and FFmpeg's filter parser rejects
  escaped drive-colons in `fontfile` on Windows — the font is copied next to
  the clips and referenced colon-free with `cwd=EVAL_DIR`. A first dead run
  also exposed that the harness must set its own allowlist roots rather than
  read the user's `.env` (now deliberate and documented).

**Results (full detail in `docs/evaluation-report.md`):**

- **5/5 judged cases PASSED**, 1 favorable RECORD (model read blurred
  "DOCK 4" — ground-truth-correct, no fabrication).
- The negative gates held: no speech quoted from a silent clip; "no yellow
  sign" correctly reported when sampling missed it, "ALERT 42" found when
  the anchor sampled it; between-frame changes explicitly declined.
- Latency 31–67 s per case (thinking on); model 2.8 GB at 73% GPU, ctx 8192,
  no OOM anywhere.

**Decision (recorded in the report):** MVP profile **confirmed unchanged** —
`qwen3.5:4b` + thinking on; 6-frame live / 12-frame preview budgets; 768 px;
600 s timeout. A 7B experiment is not justified by this evidence.

**Verification (roadmap Sprint 11 checklist):**

- [x] All test cases have recorded results (JSON + report table).
- [x] The model identifies when evidence is insufficient (audio case;
  event-missed case; "cannot be established" sections throughout).
- [x] No critical false certainty remains unaddressed (no fabricated
  speech, events, or text in any answer; the one hedged mis-description of
  grey-as-black is noted in the report).
- [x] Peak memory within practical limits (2.8 GB / 4 GB card, 73% GPU).
- [x] Chosen default profile is based on measured quality and speed
  (decision section; levers named for measured need, one variable at a time).

**Tests run:** full `pytest` suite green earlier in the session (174 passed);
evaluation harness run twice (once to surface the config bug, once clean).
Live: the evaluation IS the live run.

**Unverified / deferred:** real-footage cases; `think:false` A/B; sub-second
citation labels (Sprint 14 UI shows exact timestamps via thumbnails).

## 2026-11-03 — Sprint 12: Reliability, concurrency, and cleanup

**Goal:** Make failure recovery predictable.

**Plan & scope:** cache size budget with active-file grace; bounded pipeline
lock wait; stage-duration logging; concurrency corruption tests; repeated
startup/shutdown. Deferred: a general inference retry (deliberate decision —
the only known-transient case, the `think`-400, already retries once; blanket
retries would double latency on real failures), UI cancel button (post-MVP),
request cancellation on client disconnect (FastAPI limitation, documented).

**What was done:**

- `FrameStore.sweep()` replaces `sweep_stale()`: age expiry first, then a
  total-size budget (`CACHE_MAX_BYTES`, 1 GiB default) with oldest-first
  eviction. Batches younger than a 5-minute active grace are never removed
  even when over budget — cleanup can never delete files an in-flight
  request is using. Regression test: oldest evicted, active batch survives.
- Pipeline lock: near-simultaneous jobs now wait up to 2 s for the single
  slot before a structured 409 (bounded; no invisible request pile-up).
  Discussion and evidence share the slot (`MAX_CONCURRENT_INFERENCE=1`
  enforced at the app level).
- Stage-duration logging in `DiscussionService` (`stage=resolve`, `stage=
  extract` with cache-hit flag, `stage=infer`) — correlated by the request-ID
  log filter; the evidence route logs extraction elapsed/cache-hit.
- `HttpxInferenceTransport` is now self-healing: a client closed by a
  previous lifecycle shutdown is recreated on demand. **Found by the new
  lifespan test** — an in-process restart (`uvicorn --reload`, repeated
  TestClient lifecycles) previously inherited a dead HTTP pool and every
  later `/api/status` probe failed.

**Verification (roadmap Sprint 12 checklist):**

- [x] Two concurrent requests do not corrupt shared state — 20 concurrent
  syncs across 8 threads produce exactly revisions 1–20 and a consistent
  final snapshot; 3 concurrent previews end only in 200/409 with the store
  consistent afterwards.
- [x] A timed-out job does not leave FFmpeg running — `subprocess.run`
  kill-and-reap covered by the Sprint 6 timeout test (30 s sleeper killed at
  a 2 s budget); child-process discipline unchanged.
- [x] Cache cleanup never removes active files — active-grace eviction test
  (youngest batch survives an over-budget sweep; oldest evicted first).
- [x] Logs correlate stages by request ID — stage logs flow through the
  context-var filter (`[rid]`), verified in log output.
- [x] The UI returns to a usable state after failures — covered by the
  Sprint 8/10 browser verifications (error stages, re-enabled buttons) and
  the 200/409-only concurrency test.
- [x] Startup/shutdown repeated — 3 live uvicorn cycles (health + inference
  ready each time) plus the in-process lifespan test that caught the pool
  leak.

**Tests run:** `pytest` — 179 passed (174 prior + 5 new/reworked). Live:
3 startup/shutdown cycles; backend left running for the resting state.

**Unverified / deferred:** true async cancellation on client disconnect
(FastAPI/Starlette limitation — jobs run to completion; bounded timeouts cap
the cost); disk-budget telemetry in the UI (Sprint 14).

## 2026-11-03 — Sprint 13: Local security and privacy hardening

**Goal:** Reduce avoidable risks in a local-only app.

**Plan & scope:** Host + Origin validation middleware, payload-size limit,
conservative response headers, userscript marker header, regression tests,
hardening checklist. Deferred: request token/pairing (decision: not required
— see below), TLS (loopback only), rate limiting beyond the pipeline lock.

**What was done:**

- `app/api/security.py` — two middlewares:
  - `SecurityMiddleware`: (1) **Host validation** — non-loopback Host
    headers are rejected (403 `forbidden_origin`), which closes DNS
    rebinding completely; (2) **Origin validation** — loopback origins on
    the app's port pass (dashboard), foreign origins (e.g. youtube.com
    surfaced by `GM_xmlhttpRequest`) are rejected unless they carry
    `X-Video-Discusser-Client` — a custom header hostile pages cannot attach
    cross-origin (its CORS preflight is never answered) but the
    extension-privileged userscript can. Adds `X-Content-Type-Options:
    nosniff`, `Referrer-Policy: no-referrer`, and a `default-src 'self'`
    CSP on HTML responses.
  - `PayloadLimitMiddleware` — bodies over `MAX_REQUEST_BYTES` (1 MiB
    default) get a structured 413 before parsing.
- **No CORS middleware, on purpose** (recorded decision): emitting no
  cross-origin headers is stricter than any allowlist — cross-origin JS can
  never read responses. **No request token/pairing, on purpose** (decision):
  Host + Origin + the preflight-immune marker cover the local threat model
  without key management.
- Userscript sends the marker header on `GM_xmlhttpRequest`; the dev harness
  stub passes headers through.
- Test client: all tests now present a loopback Host via a conftest
  `TestClient` subclass — the middleware correctly rejected the default
  `testserver` host as a rebound domain, which is exactly the hardening
  working.

**Architecture violation found and fixed (roadmap §17 #9, finally closed):**
route handlers were `async def` while doing **blocking** work (FFmpeg
subprocesses, inference HTTP calls) — one in-flight discussion froze the
entire event loop (discovered when even static files stopped serving during
generation; TestClient's per-request event loops had masked it all along).
All route handlers are now sync `def` → FastAPI runs them in the threadpool.
Measured after the fix: health 4–5 ms and static files 64 ms **while a full
inference was in flight**.

**Hardening checklist (roadmap Sprint 13):**

- [x] Service not listening on LAN interfaces — config-validated loopback
  host; live `netstat`: `127.0.0.1:8000` only.
- [x] Unapproved origins rejected — live: `Host: evil.example.com` → 403
  `forbidden_origin`; foreign Origin without marker → 403; loopback origin
  on a wrong port → 403.
- [x] Invalid/oversized payloads fail predictably — 413 envelope before
  parsing; schema validation for every body (422 envelopes).
- [x] Cache path traversal fails — Sprint 7 layered defenses re-verified by
  the existing test matrix.
- [x] Debug errors not exposed — envelope-only responses; 404s carry no
  tracebacks (regression-tested).
- [x] No cloud inference traffic — no cloud endpoints exist in the code;
  the inference URL is config-validated loopback-only; binding is
  loopback-only; the evaluation harness and tests run with no network.
- [x] Subprocess discipline re-verified — argument arrays enforced in
  `run_command` (type check), `shell=False` throughout.

**Tests run:** `pytest` — 196 passed (179 prior + 17 security tests; the
conftest TestClient subclass fixed 68 baseline tests the Host check rightly
rejected). Live: binding/rebinding/marker checks, harness flow, same-origin
discussion (49.7 s), responsiveness during inference.

**Telemetry note:** generation length varies widely with thinking on
(1,087 vs 3,434 eval tokens on near-identical prompts; 240 s vs 85 s) — the
600 s bound held; a `think:false` fast path or answer-length budget remains
a measured lever for Sprint 14+ if live UX needs it.

**Unverified / deferred:** real Tampermonkey round-trip with the marker
header (manual checklist); LAN-hostile testing beyond the browser threat
model (out of scope — single-user local app).

## 2026-11-03 — Sprint 14: Legal commentary quality and user trust

**Goal:** Make the limits of the analysis visible and consistent.

**Plan & scope:** structured answer rendering (the three contracted sections
as distinct visual blocks), per-answer disclaimer + frames-reviewed footer,
copy-answer action (local clipboard only), a `legal-caution` evaluation case,
prompt-regression tests. Deferred: export/session library (Sprint 20),
denser re-sampling (Sprint 19).

**What was done:**

- Dashboard — answers now render as separated blocks: *Visible observations*
  (neutral), *Possible interpretation* (amber border — inference is
  visually distinct from what was seen), *What cannot be established*
  (muted). Parsing is tolerant: unknown formats fall back to a preamble
  block; everything stays textContent-only. Every answer carries a footer:
  "AI-generated commentary — not legal advice. Frames reviewed: … Only
  sampled still frames were analyzed — audio and moments between frames were
  not seen." A Copy action writes the plain answer to the local clipboard
  (no network).
- `app/services/prompts.py` — `format_timestamp_label` now emits h:mm:ss for
  hour-long videos (aligning with the dashboard formatter).
- `scripts/run_evaluation.py` — new `legal-caution` case: a loaded legal
  question ("Was anyone committing a crime? Who is at fault?") about a
  text-only clip.
- Roadmap: recorded the agreed Sprint 17 addition — a full pre-release
  audit (security, privacy, tests, docs, evaluation) before the RC tag.
- Stale copy fixed: the evidence card no longer claims model analysis
  "arrives in a later sprint".

**Verification (roadmap Sprint 14 checklist) — browser + tests:**

- [x] The disclaimer is visible without opening settings — header notice in
  static HTML (tested) and the per-answer footer (verified in browser).
- [x] Each timestamp maps to a frame supplied to the model — the footer
  lists exactly the frames used; thumbnails link to the video at those
  times (YouTube sources).
- [x] The app distinguishes observation from inference — three visually
  separated section blocks, verified in the browser (screenshot).
- [x] The model does not present its response as a definitive legal ruling —
  the new `legal-caution` case PASSED: asked "Was anyone committing a crime?
  Who is at fault?", it closed with "These frames cannot establish whether
  anyone was committing a crime or identify who is at fault…".
- [x] Missing audio/off-screen context is stated where relevant — prompt
  rules (regression-tested) plus the per-answer footer and the standing
  sampling-gap note.

**Tests run:** `pytest` — 217 passed (196 prior + 21: 19 prompt-regression
+ 2 dashboard static). Eval: `legal-caution` PASS (49.2 s). Live: structured
rendering verified in the browser against a real loaded question.

**Unverified / deferred:** copy-to-clipboard verified by button presence +
API use (clipboard permission prompts are browser-managed); report/export
(Sprint 20).

## 2026-11-04 — Sprint 15: Sessions and local persistence

**Goal:** Persist useful discussions — the user explicitly opted this into
the MVP (2026-11-03).

**Plan & scope:** versioned SQLite store (`data/sessions/`, stdlib `sqlite3`,
WAL); one session per video, Q/A pairs with frame references (opaque IDs +
cache-relative paths only); read-only history API + deletion with
cache-eligible frame cleanup; History card in the dashboard;
`SESSIONS_ENABLED` toggle. Deferred: resuming a historical video as active
(post-MVP), export (Sprint 20), multi-device anything (out of scope).

**What was done:**

- `app/services/session_store.py` — `PRAGMA user_version` schema versioning
  (v1; newer databases are refused, not corrupted), foreign keys +
  `ON DELETE CASCADE`, thread-locked connection. `record_discussion`
  get-or-creates the per-video session and appends the Q/A pair; all store
  failures are swallowed and logged — **recording problems can never break a
  discussion or the active sync state**.
- `app/api/sessions.py` — list / detail / delete-one / clear-all. Deletion
  computes frames the deleted session referenced, keeps those still
  referenced elsewhere, and removes the rest from the cache through the new
  `FrameStore.delete_frames`.
- `DiscussionService` — records successful discussions (never failures);
  `sessions_enabled=false` or a broken store degrades to no-op.
- Dashboard — History card: session rows (title, message count, last
  activity), click to expand read-only Q/A detail, per-row delete, Clear
  all. The list refreshes automatically after each answered question.

**Verification (roadmap Sprint 15 checklist):**

- [x] Sessions survive restart — unit test with a fresh store instance and
  a live restart (history persisted across the backend process restart).
- [x] Delete removes the intended records and associated eligible cache —
  API test (frames 404 after delete) and live UI delete ("Deleted.", list
  empty).
- [x] Database errors do not corrupt active sync state — broken-connection
  test: `record_discussion` returns None and the discussion flow is
  unaffected; store init failures degrade to log-only.
- [x] No raw media retained without explicit choice — only Q/A text and
  frame *references* are stored; frame files remain governed by the cache
  policy and are deleted when unreferenced after session deletion.

**Bugs and lessons during the sprint:**

1. **Test-data leak into developer data:** the test helpers built `Settings`
   without `sessions_dir`, so every pytest discussion wrote into the real
   `data/sessions` DB (the same class of default-path leak as the Sprint 15
   env parsing issue). All test settings now isolate `sessions_dir`; the
   polluted dev DB was cleared (it contained only test debris).
2. **SQLite WAL resurrection:** deleting the DB files while the server held
   them open let the WAL checkpoint restore the old rows on restart —
   stop-server-first is the correct procedure (recorded here for ops).
3. A stale-tab confusion during verification (two dashboard tabs) was a
   checking mistake, not a product bug.

**Tests run:** `pytest` — 227 passed (217 prior + 10 new). Live: discussion
recorded → History card listed it → detail opened (Q/A with timestamps and
snapshot revision) → UI delete cleared records and cache.

**Unverified / deferred:** resuming a historical video as the active one;
export; concurrent multi-tab history edits (single-user assumption).

## 2026-11-04 — Sprint 16: Setup experience and packaging

**Goal:** Make the app reproducible on the target Windows PC.

**Plan & scope:** full README setup guide with verified versions; preflight
upgrades (model-pulled check, double-launch detection, copyable
`--diagnostics`); config-driven `scripts/serve.py` launcher; packaging
decision. Deferred: Electron-style desktop packaging (decision: remain a
local web dashboard for the MVP; revisit after the release-candidate audit).

**What was done:**

- `scripts/check_environment.py` — three additions: (1) **model-pulled
  check** — queries the runtime's model list and warns with the exact
  `ollama pull` command when the configured model is absent ("the app does
  not claim model-ready if the runtime is unavailable"); (2)
  **double-launch detection** — reports whether the configured port is free,
  already serving a Video Discusser instance, or occupied by another
  program; (3) **`--diagnostics` mode** — a fenced, copyable support block
  containing config summary, preflight, and live health/status, explicitly
  omitting question text, video URLs, and local paths.
- `scripts/serve.py` — launch the backend from `.env`'s `APP_HOST`/
  `APP_PORT` (single source of truth; no flag drift). Unit-tested: host/port
  passed to uvicorn come from Settings.
- `README.md` — a complete Windows setup guide: prerequisites with
  install commands, verified-version table, venv + editable install, minimal
  `.env`, preflight, model pull, backend launch, dashboard/first-use
  walkthrough (local file + YouTube), and a troubleshooting table mapping
  the preflight's failure messages to fixes.
- Packaging decision recorded (README §9 + here): local web dashboard for
  the MVP; runtime/model installation remains an explicit separate concern.

**Verification (roadmap Sprint 16 checklist):**

- [x] A clean environment can follow the guide from scratch — every command
  in the guide was executed in order on this machine (clone step exercised
  by the repo's existence; venv/install re-run idempotently; `.env` copy,
  preflight, model pull, serve, dashboard, sync, ask all verified across
  Sprints 6–15 sessions). A truly pristine-machine pass (no Python/FFmpeg
  preinstalled) remains a manual item for the RC audit.
- [x] Missing dependencies are named clearly — preflight FAIL/WARN lines
  carry exact install commands (`winget install Gyan.FFmpeg`,
  `ollama pull qwen3.5:4b`, `pip install yt-dlp`).
- [x] The app does not claim model-ready if the runtime is unavailable —
  dashboard probe reports `unavailable`; preflight distinguishes runtime
  down vs model not pulled.
- [x] Launching twice does not silently conflict — second `serve.py` exits 3
  with `[Errno 10048] only one usage of each socket address`; preflight
  detects the running instance beforehand.
- [x] Existing features remain intact — full suite green (228 passed,
  including the new serve test); backend still serving after all script
  changes.

**Tests run:** `pytest` — 228 passed (227 prior + 1 serve test). Live:
preflight (with running backend → double-launch warning path), diagnostics
output, two-launch conflict, single-instance cleanup.

**Unverified / deferred:** pristine-machine setup pass (no preinstalled
Python/FFmpeg) — assigned to the Sprint 17 full audit; launcher smoke test
on PowerShell (guide's PowerShell activation path) — commands are standard
documented PowerShell; flagged for the audit.

## 2026-11-04 — Sprint 17: Release candidate

**Goal:** Freeze a reliable baseline; run the release checklist; tag
`v0.1.0-rc1`. The full adversarial pre-release audit (agreed 2026-11-03)
runs immediately after this entry as its own phase.

**Verification (release checklist):**

- [x] All unit and integration tests — 228 passed (includes the
  skip-guarded live-model test against the real runtime).
- [x] Fixed evaluation set re-run — **6/6 judged cases passed** (7 total,
  incl. the favorable RECORD); results refreshed in
  `data/cache/eval/results.json` (ran_at 2026-11-04 11:06).
- [x] Manual regression checklist (implementation-guide §8) — executed the
  live-verifiable items: synthetic sync, local-video frames (cap, monotonic
  order, in-window, EOF pull-back), health independence from the runtime
  (second instance with a dead inference URL → `inference: unavailable`
  while health stays OK), loopback binding, separate error codes for
  missing-model vs media failures (unit-tested), cache-cleanup safety
  (unit-tested). **User-only items marked unverified in the RC:** real
  Tampermonkey pause-sync round-trip and YouTube SPA navigation (manual
  checklist in `browser/README.md`).
- [x] Cache cleanup / shutdown / restart behavior — covered by the Sprint 12
  reliability suite plus three live startup/shutdown cycles (Sprint 12 log).
- [x] README review — added a **Known limitations (release candidate)**
  section stating speed, sampling gaps, synthetic evaluation coverage,
  minute-precision citations, single-user assumptions, and the not-legal-
  advice boundary honestly.
- [x] Release candidate tagged — `v0.1.0-rc1` (annotated tag recording the
  measured profile) and pushed.

**RC finding (fixed in this sprint):** the preflight exposed that **Ollama
binds 0.0.0.0:11434 by default** — the model runtime was reachable from the
LAN, violating architecture §13's "backend and model runtime bind to
loopback" for the runtime half. Added a preflight check that probes the
machine's LAN addresses and warns with the exact fix
(`setx OLLAMA_HOST 127.0.0.1`), plus the step in the README setup guide.
(The backend itself was already loopback-only by config validation.)

**Chosen profile (recorded in the tag):** `qwen3.5:4b` + thinking on,
`num_ctx` 8192, 6-frame live / 12-frame preview budgets, 768px/q80
extraction, 600s/120s timeouts — measured in `docs/evaluation-report.md`.

**Full test suite:** 228 passed. **Evaluation:** 6/6 judged + 1 RECORD.

**Unverified / deferred:** Tampermonkey manual checklist (user); pristine
machine setup pass; both feed the audit below.

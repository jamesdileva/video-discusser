# Video Discusser & Legal Commentary Agent — Sprint Roadmap

**Status:** Proposed implementation sequence  
**Version:** 1.0  
**Last updated:** 2026-10-13

This roadmap expands the supplied architecture into small, verifiable steps. Complete the verification gate at the end of each sprint before moving on. The early sprints deliberately avoid coupling the application to a large VLM before the hardware and API path are proven.

## Delivery principles

- Build one working vertical slice at a time.
- Preserve working features when changing files; prefer targeted edits and tests over wholesale replacements.
- Keep external services behind adapters so a model/runtime or media-source change does not require rewriting routes.
- Do not claim video understanding until a known-frame test succeeds.
- Prefer deterministic tests and mocked adapters for most development; reserve GPU/model tests for explicit gates.
- Every sprint ends with a known working state and a short test record.

## Milestone map

| Milestone | Sprints | Exit outcome |
|---|---:|---|
| M0 — Baseline and feasibility | 0–2 | Repository, environment, ports, model/runtime plan validated |
| M1 — API and browser sync | 3–5 | Pause event reliably updates the dashboard |
| M2 — Evidence pipeline | 6–8 | Bounded timestamped frames extracted and shown |
| M3 — Local inference | 9–11 | Real frame-grounded discussion works on a fixed test set |
| M4 — Quality and reliability | 12–14 | Errors, resource caps, cache, and evidence limitations are handled |
| M5 — Usable MVP | 15–17 | Polished local workflow, repeatable setup, release checklist |
| M6 — Optional expansions | 18+ | History, transcript support, richer source support, packaging |

---

## Sprint 0 — Repository inventory and baseline

### Goal
Establish what exists and prevent accidental replacement of useful work.

### Tasks
1. Create a Git branch for the architecture implementation.
2. Inventory existing files, dependencies, scripts, and any working prototype.
3. Compare existing code against `architecture.md`; list differences instead of overwriting blindly.
4. Create `README.md`, `.gitignore`, and `.env.example` if absent.
5. Ensure generated media, `.env`, virtual environments, model files, logs, and local databases are ignored by Git.
6. Record Windows version, Python version, FFmpeg availability, yt-dlp availability, GPU/VRAM, and available disk space.

### Deliverables
- Baseline inventory note
- Clean repository layout or a migration checklist
- `.gitignore` and `.env.example`

### Verification
- [ ] Existing work is committed or backed up.
- [ ] No secrets, model weights, cache media, or local databases are staged.
- [ ] `git status` is understood and clean after the baseline commit.
- [ ] Dependency/tool inventory is recorded.

### Exit gate
Do not restructure files until the existing state is recoverable.

---

## Sprint 1 — Hardware and runtime feasibility spike

### Goal
Prove a small local vision model can accept images on the target machine before building around it.

### Tasks
1. Choose one Windows-friendly runtime candidate, starting with `llama.cpp`/`llama-server` if a supported model artifact is available.
2. Pick one small quantized VLM candidate supported by that runtime. Treat model names and quantizations as candidates, not commitments.
3. Install the runtime in isolation from the FastAPI application.
4. Start the inference service on `127.0.0.1:8081`; verify its health/model-list endpoint if supported.
5. Send a single known image with a simple prompt using the exact request format documented by the runtime.
6. Record model artifact, quantization, runtime version, startup time, response time, peak VRAM/RAM, and any limitations.
7. Test one image and a small multi-image request if supported. Do not start with 45 frames.
8. Document a fallback candidate if the first runtime/model combination fails.

### Deliverables
- `docs/runtime-feasibility.md`
- A reproducible smoke-test request/script
- Chosen runtime/model candidate or a documented blocker

### Verification
- [ ] Runtime starts reliably after restart.
- [ ] Single-image question returns a coherent response.
- [ ] Multi-image behavior is known, or the limitation is documented.
- [ ] Peak memory and latency are measured, not guessed.
- [ ] No cloud endpoint is used.
- [ ] The chosen path does not require unsupported Windows-only assumptions.

### Exit gate
Do not implement the inference adapter against an untested payload schema.

---

## Sprint 2 — Project skeleton and configuration

### Goal
Create a small, testable FastAPI application with configuration centralized.

### Tasks
1. Create the `app/` package and module layout from `architecture.md`.
2. Add pinned dependencies in one authoritative file (`pyproject.toml` recommended).
3. Add `app/config.py` with settings for:
   - backend host/port
   - inference base URL
   - cache directory
   - analysis window and maximum frame count
   - maximum image dimension and JPEG quality
   - extraction and inference timeouts
   - maximum concurrent jobs
4. Validate configuration at startup and give actionable errors for invalid paths/ports.
5. Add `GET /api/health`.
6. Serve the static dashboard from FastAPI or document the chosen local-serving approach.
7. Add request IDs and structured logging foundations.

### Deliverables
- Running app skeleton
- `.env.example`
- Initial test suite

### Verification
- [ ] `GET /api/health` returns 200 and version.
- [ ] Invalid configuration fails with a clear message.
- [ ] Backend listens on `127.0.0.1:8000`.
- [ ] Runtime URL defaults to a different port.
- [ ] `pytest` runs without requiring a GPU or network.
- [ ] Logs do not include user questions or full URLs by default.

---

## Sprint 3 — Sync schema and active-video service

### Goal
Make video state valid, testable, and race-aware.

### Tasks
1. Implement `SyncPayload` with URL, timestamp, optional video ID, and sync source.
2. Parse URL using a URL parser; allow only approved YouTube hostnames and schemes for YouTube sync.
3. Parse `v=` and supported short-link forms carefully; reject unrelated hosts.
4. Reject NaN, infinity, negative timestamps, empty URLs, and oversized inputs.
5. Implement an `ActiveVideoService` with immutable snapshots and a revision counter.
6. Implement `POST /api/sync` and `GET /api/status`.
7. Add structured error responses and tests.

### Deliverables
- Sync/status endpoints
- Active-video service
- URL and timestamp validation tests

### Verification
- [ ] Valid URL/timestamp updates state.
- [ ] Invalid URL and timestamp return 4xx responses.
- [ ] Re-sync increments revision.
- [ ] Status returns `null` state before first sync.
- [ ] URL parsing works when extra query parameters are present.
- [ ] A stale request cannot silently overwrite a newer snapshot without incrementing revision.

---

## Sprint 4 — Dashboard shell and service status

### Goal
Create the first usable local dashboard before adding inference.

### Tasks
1. Build `index.html`, `styles.css`, and `app.js`.
2. Add active video, timestamp, last-sync time, backend status, inference status, and media-tool status.
3. Add an empty chat area and disabled question input until video state exists.
4. Poll `/api/status` every 2–3 seconds; pause polling when the tab is hidden if practical.
5. Display stale/offline states rather than leaving old status as if current.
6. Use `textContent` for dynamic user/model text. Do not inject model output as HTML.
7. Add loading, empty, and error states.

### Deliverables
- Functional dashboard shell
- Status rendering

### Verification
- [ ] Dashboard loads without JavaScript errors.
- [ ] No synced video displays a clear empty state.
- [ ] Posting a test sync updates the dashboard.
- [ ] Backend shutdown shows disconnected state.
- [ ] User/model text is rendered as text, not HTML.
- [ ] Layout remains usable at common desktop window sizes.

---

## Sprint 5 — YouTube userscript synchronization

### Goal
Make the real pause-to-sync workflow reliable.

### Tasks
1. Create `browser/youtube-sync.user.js` with correct userscript metadata.
2. Handle YouTube single-page navigation and delayed video-element creation.
3. Observe the `pause` event in capture mode and read `currentTime` at event time.
4. Debounce repeated events and avoid posting duplicate unchanged state unnecessarily.
5. Send requests to the configured backend origin and handle offline/CORS failures.
6. Add a manual “Sync now” option if pause events prove unreliable.
7. Add a visible, unobtrusive userscript status indicator if it can be implemented without breaking the page.
8. Document Tampermonkey setup and permissions.

### Deliverables
- Browser sync userscript
- Setup instructions
- Manual test checklist

### Verification
- [ ] Pause sends the correct URL and timestamp.
- [ ] Play/resume/pause cycles update state.
- [ ] Navigating to another video in the same tab works without refresh.
- [ ] Pausing near 0 seconds is valid.
- [ ] Backend offline does not break YouTube playback.
- [ ] Other websites are not targeted by the script.

---

## Sprint 6 — Media-source adapter and environment checks

### Goal
Isolate source access and make extraction failures understandable.

### Tasks
1. Define a `MediaSource` interface for resolving a source and extracting frames for a requested interval.
2. Implement local-file source support first, using a user-selected path from trusted local configuration/UI. Do not accept arbitrary filesystem paths from browser requests.
3. Implement an optional YouTube source adapter using yt-dlp where permitted and available.
4. Validate the URL/host before handing it to yt-dlp.
5. Use subprocess argument arrays, timeouts, bounded stderr capture, and explicit return-code checks.
6. Add `scripts/check_environment.py` to check FFmpeg, yt-dlp, cache directory writability, runtime reachability, and configured ports.
7. Provide clear guidance when a source is unavailable or access is restricted; do not bypass DRM or access controls.

### Deliverables
- Media adapter interface
- Local-file extraction
- Optional YouTube extraction
- Environment check script

### Verification
- [ ] Local sample video can be probed and read by FFmpeg.
- [ ] Unsupported URLs are rejected before invoking external tools.
- [ ] Missing FFmpeg produces an actionable error.
- [ ] yt-dlp failure does not crash the API process.
- [ ] Child processes time out and terminate correctly.
- [ ] No command is built by concatenating untrusted URL text into a shell string.

---

## Sprint 7 — Frame extraction and bounded sampling

### Goal
Produce timestamped, inspectable frames within a strict resource budget.

### Tasks
1. Implement analysis window calculation, clamping the start to zero.
2. Extract frames at candidate timestamps using FFmpeg.
3. Resize while preserving aspect ratio and encode JPEGs at configured quality.
4. Enforce the maximum frame count independently of user-supplied parameters.
5. Always attempt to include the anchor frame and distribute other samples across the window.
6. Record timestamp, generated frame ID, dimensions, and hash.
7. Verify every output exists and is non-empty; do not rely only on FFmpeg's exit code.
8. Create safe frame-preview serving through `/api/frames/{frame_id}`.
9. Add cache keys and a simple stale-entry cleanup routine.

### Deliverables
- `frame_extraction.py`
- `frame_sampling.py`
- Frame metadata schemas
- Frame preview endpoint

### Verification
- [ ] A 180-second window stays within the configured frame cap.
- [ ] A timestamp before 180 seconds produces a start time of zero.
- [ ] Frame timestamps are monotonic and within the requested window.
- [ ] Empty/corrupt extraction returns a clear error.
- [ ] Traversal attempts and unknown frame IDs are rejected.
- [ ] Preview images display in the dashboard.
- [ ] Cache keys change when sampling settings change.

---

## Sprint 8 — Evidence preview and question workflow UI

### Goal
Let the user inspect what the model will actually see.

### Tasks
1. Enable the question field when a valid active-video snapshot exists.
2. Add a bounded window selector (start with default window and a small set of options).
3. Show the operation stages: preparing source, extracting frames, preparing prompt, inference, complete.
4. Show frame thumbnails and clickable timestamps linked to the original video.
5. Add cancel/retry behavior where feasible.
6. Disable duplicate submits while a request is active.
7. Explain that sampled frames can miss events between them.

### Deliverables
- Evidence preview UI
- Question submission states
- Error and cancellation states

### Verification
- [ ] The user can see frame timestamps before/after model analysis.
- [ ] Duplicate submissions are prevented or handled safely.
- [ ] A failed extraction does not leave the UI permanently loading.
- [ ] A changed video is visually distinguishable from the prior snapshot.
- [ ] The UI clearly identifies the active analysis window.

---

## Sprint 9 — Inference adapter

### Goal
Integrate the chosen runtime without coupling API routes to runtime-specific details.

### Tasks
1. Implement `InferenceAdapter` and `RuntimeCapabilities`.
2. Add a health check and a startup/status probe.
3. Implement the exact image-input format proven in Sprint 1.
4. Convert selected frames into the required payload form without exceeding request limits.
5. Add connect/read timeouts and map runtime failures to application errors.
6. Validate response structure; handle empty choices/content and malformed responses.
7. Add mocked adapter tests so CI does not need the model.
8. Keep the runtime port separate from FastAPI.

### Deliverables
- `inference.py`
- Runtime health status
- Mocked tests and a real smoke test

### Verification
- [ ] Health probe reports ready/unavailable accurately.
- [ ] One known image can be sent through the adapter.
- [ ] Missing runtime returns `503 inference_unavailable`.
- [ ] Timeout returns `504 inference_timeout`.
- [ ] Invalid response content is handled.
- [ ] Backend does not assume video-input support when only image input was verified.

---

## Sprint 10 — Discussion orchestration and evidence-aware prompting

### Goal
Produce a response grounded in the frames selected for this request.

### Tasks
1. Implement `DiscussionService` to snapshot active state and orchestrate media, sampling, and inference.
2. Enforce maximum question length, window length, frame count, context turns, and concurrency.
3. Add a system prompt that separates visible observations from interpretations.
4. Require timestamp references and explicit uncertainty when evidence is incomplete.
5. Do not ask the model to infer audio, off-screen events, identity, intent, or exact unseen actions from silent still images.
6. Include a concise disclaimer for legal/procedural questions.
7. Check the active-video revision after processing and tag the result to the original snapshot.
8. Implement `POST /api/discuss` with structured responses/errors.

### Deliverables
- Working discussion endpoint
- Prompt templates
- Orchestration tests

### Verification
- [ ] A mocked end-to-end request returns answer plus frame references.
- [ ] Missing active video returns a useful 4xx error.
- [ ] Model response cites only timestamps supplied to it.
- [ ] Unsupported questions are answered with limitations rather than invented facts.
- [ ] A video change during inference does not relabel the old answer as the new video's answer.
- [ ] Inference and media failures map to distinct error codes.

---

## Sprint 11 — First real end-to-end model evaluation

### Goal
Prove the entire workflow with known videos and record where it fails.

### Tasks
1. Prepare a small, lawful test set with known timestamps and questions.
2. Include clear visual facts, ambiguous moments, an audio-dependent question, and a question about an event between sampled frames.
3. Run each case with the same model/runtime and frame budget.
4. Record answer quality, unsupported claims, missed events, latency, peak memory, and extraction failures.
5. Adjust resolution/frame count only one variable at a time.
6. If quality is insufficient, test a second small model or revise sampling before increasing to 7B.
7. Keep examples and evaluation notes local; avoid storing sensitive footage without explicit intent.

### Deliverables
- `docs/evaluation-report.md`
- Repeatable manual or scripted test set
- Model/frame-budget decision

### Verification
- [ ] All test cases have recorded results.
- [ ] The model identifies when evidence is insufficient.
- [ ] No critical false certainty remains unaddressed.
- [ ] Peak memory is within the machine's practical limits.
- [ ] Chosen default profile is based on measured quality and speed.

### Exit gate
Do not call the MVP complete if the model frequently invents unseen actions or if the resource profile makes normal use impractical.

---

## Sprint 12 — Reliability, concurrency, and cleanup

### Goal
Make failure recovery predictable.

### Tasks
1. Add a one-job-at-a-time queue or semaphore for inference and media processing.
2. Ensure cancellation/timeout terminates child processes and releases resources.
3. Add request IDs and stage-level duration logging.
4. Add cache size/age limits and safe cleanup.
5. Add a single bounded retry only for clearly transient runtime errors, if useful.
6. Make UI errors actionable and avoid showing stack traces.
7. Test startup and shutdown repeatedly.

### Deliverables
- Bounded job orchestration
- Cleanup policy
- Reliability tests

### Verification
- [ ] Two concurrent requests do not corrupt shared state.
- [ ] A timed-out job does not leave FFmpeg running.
- [ ] Cache cleanup never removes active files.
- [ ] Logs correlate stages by request ID.
- [ ] The UI returns to a usable state after failures.

---

## Sprint 13 — Local security and privacy hardening

### Goal
Reduce avoidable risks in a local-only app.

### Tasks
1. Bind services to loopback by default.
2. Replace wildcard CORS with the exact dashboard origin(s).
3. Validate Host and Origin headers and test browser-origin behavior.
4. Limit payload sizes and validate every API schema.
5. Validate frame IDs and resolve paths beneath the cache root.
6. Confirm subprocess invocation never uses `shell=True` for user-controlled values.
7. Ensure no prompt, video URL, or media is sent to an external AI provider.
8. Review logging, Git ignore rules, cache retention, and error output.
9. Add a local request token/pairing approach only if required by the tested browser-origin design.

### Deliverables
- Hardening checklist
- Regression tests
- Updated privacy notes

### Verification
- [ ] Service is not listening on LAN interfaces by default.
- [ ] Unapproved origins are rejected.
- [ ] Invalid/oversized payloads fail predictably.
- [ ] Cache path traversal fails.
- [ ] Debug errors are not exposed to ordinary browser responses.
- [ ] Network inspection confirms no cloud inference traffic.

---

## Sprint 14 — Legal commentary quality and user trust

### Goal
Make the limits of the analysis visible and consistent.

### Tasks
1. Add a persistent “commentary, not legal advice” notice.
2. Add a response layout separating:
   - Visible observations
   - Possible interpretations
   - Unknowns / missing context
   - Frames reviewed
3. Ensure the prompt and UI do not imply the model saw every moment or heard audio.
4. Add an easy way to open the original video at a cited timestamp.
5. Test sensitive questions about intent, legality, consent, threat, or causation for cautious handling.
6. Add a report/copy response action only if it does not undermine privacy defaults.

### Deliverables
- Evidence-aware response UI
- Prompt regression tests

### Verification
- [ ] The disclaimer is visible without opening settings.
- [ ] Each timestamp maps to a frame supplied to the model.
- [ ] The app distinguishes observation from inference.
- [ ] The model does not present its response as a definitive legal ruling.
- [ ] Missing audio/off-screen context is stated where relevant.

---

## Sprint 15 — Sessions and optional local persistence

### Goal
Persist useful discussions only if the MVP needs it.

### Tasks
1. Decide whether users need history before adding a database.
2. If yes, implement SQLite storage for session metadata, messages, frame references, and model profile.
3. Store relative paths/IDs, not absolute paths as public identifiers.
4. Add delete-session and clear-cache behavior.
5. Keep raw video retention disabled by default.
6. Add schema versioning and safe initialization.

### Deliverables
- Optional SQLite session store
- History UI
- Delete/retention controls

### Verification
- [ ] Sessions survive restart if persistence is enabled.
- [ ] Delete removes the intended records and associated eligible cache.
- [ ] Database errors do not corrupt active sync state.
- [ ] No raw media is retained without explicit user choice.

**If history is not needed for the first release, defer this sprint.**

---

## Sprint 16 — Setup experience and packaging

### Goal
Make the app reproducible on the target Windows PC.

### Tasks
1. Document dependency installation and verified versions.
2. Add a startup preflight for Python, FFmpeg, optional yt-dlp, cache directory, and inference runtime.
3. Provide a clear startup sequence: start model runtime, start backend, open dashboard, install userscript.
4. Add copyable diagnostics that omit private URLs and question text.
5. Decide whether to remain a local web dashboard or package with Electron only after MVP stability.
6. If packaging is selected, preserve all web-dashboard functionality and keep runtime/model installation as an explicit separate concern.

### Deliverables
- `README.md` setup guide
- Preflight script
- Repeatable launch process

### Verification
- [ ] A clean environment can follow the guide from scratch.
- [ ] Missing dependencies are named clearly.
- [ ] App does not claim model-ready if the runtime is unavailable.
- [ ] Launching twice does not silently start conflicting servers.
- [ ] Existing features remain intact after any packaging work.

---

## Sprint 17 — MVP release candidate

### Goal
Freeze a reliable baseline before adding ambitious features.

### Tasks
1. Run all unit and integration tests.
2. Run the full manual checklist on the target PC.
3. Run the fixed evaluation set.
4. Verify cache cleanup, app shutdown, and restart behavior.
5. Review README, known limitations, privacy behavior, and source-access terms.
6. Tag a release candidate and record the chosen model/runtime settings.

### Release acceptance criteria
- [ ] Pause-to-sync works across YouTube single-page navigation.
- [ ] Dashboard reports backend and runtime readiness separately.
- [ ] The user can inspect timestamped frames.
- [ ] A question produces a grounded response from a tested local VLM.
- [ ] Frame and concurrency limits are enforced.
- [ ] Errors are understandable and do not leave stuck jobs.
- [ ] No cloud AI API is used.
- [ ] The default binding is loopback-only.
- [ ] Legal limitations and sampling gaps are visible.
- [ ] The setup guide is reproducible.

---

# Optional post-MVP roadmap

## Sprint 18 — Transcript and audio support

Only proceed if the user needs questions that depend on spoken dialogue. Add an explicit transcript/audio pipeline, time-aligned segments, and source attribution. Do not infer dialogue from silent frames. Evaluate local speech-to-text options separately and disclose transcription uncertainty.

Verification:
- [ ] Transcript segments include timestamps.
- [ ] The UI distinguishes transcript evidence from visual evidence.
- [ ] Audio processing is opt-in and local.
- [ ] Tests cover poor audio and missing transcript cases.

## Sprint 19 — Better temporal reasoning

Add a narrow-window re-sampling workflow: when the user asks about a specific moment, extract denser frames around that timestamp rather than increasing the global frame budget.

Verification:
- [ ] User can request a focused interval.
- [ ] Sampling budget remains bounded.
- [ ] Old and new frame sets are clearly distinguished.
- [ ] Evaluation measures whether denser sampling improves accuracy.

## Sprint 20 — Session library and export

Add searchable local sessions, exportable notes, and a compact evidence timeline. Export should include model/runtime, window bounds, frame timestamps, warnings, and a clear statement that output is AI-generated commentary.

Verification:
- [ ] Export is readable and reproducible.
- [ ] Delete and retention controls work.
- [ ] Export does not accidentally embed raw video unless explicitly selected.

## Sprint 21 — Additional source integrations

Consider other video sites only after the source adapter contract and YouTube MVP are stable. Each integration needs its own permitted-access strategy and regression tests.

Verification:
- [ ] New source is isolated behind an adapter.
- [ ] Existing YouTube and local-file workflows still pass.
- [ ] Unsupported/access-restricted content fails gracefully.

## Sprint 22 — Desktop packaging

Consider Electron or another desktop wrapper if users need a single-window experience. Do not bundle model weights by default; their size, license, and hardware requirements should remain separate.

Verification:
- [ ] Dashboard capabilities are preserved.
- [ ] Backend lifecycle is managed cleanly.
- [ ] Ports, logs, cache, and shutdown are predictable.
- [ ] Installer does not expose the backend on the LAN.

## Sprint 23 — Optional larger-model profile

Try a larger model (including a 7B VLM) only if measured quality improvement justifies its memory and latency costs. This is an optional profile, not an MVP dependency.

Verification:
- [ ] Exact model artifact and runtime are documented.
- [ ] Memory and latency are measured on target hardware.
- [ ] Smaller-model profile remains available.
- [ ] Out-of-memory failure returns a recoverable error.

---

## Cross-sprint definition of done

Every sprint must leave the repository in a state that can be run and tested. Before declaring a sprint complete:

1. Run the relevant automated tests.
2. Execute the manual checks listed for the sprint.
3. Record what passed, what failed, and what remains unverified.
4. Update architecture/docs when a decision changes.
5. Confirm that earlier acceptance criteria still pass.
6. Do not mark a feature complete solely because its code exists.

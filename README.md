# Video Discusser

A **local-first** Windows desktop tool for discussing video evidence and events.

Pause a YouTube video, and a browser userscript sends the video URL and timestamp
to a local backend. The backend extracts a small, bounded set of timestamped frames
with FFmpeg and asks a **local** vision-language model — no cloud AI APIs — for an
answer grounded in what the frames actually show. A local dashboard displays the
sync state, the evidence the model was given, and the conversation.

> This tool provides commentary and research assistance. It is **not legal advice**
> and does not produce definitive findings about intent, fault, or legality.

## Status

**`v0.1.0-rc1`** tagged 2026-11-04 — sprints 0–17 complete
([`docs/sprint-roadmap.md`](docs/sprint-roadmap.md),
[`docs/dev-log.md`](docs/dev-log.md)).

| Working | Still open |
|---|---|
| Full vertical slice: userscript pause-sync, media adapters, bounded frame extraction, evidence preview, grounded answers from the local model (Sprints 0–11) | Real-Tampermonkey round-trip on live YouTube — manual checklist in [`browser/README.md`](browser/README.md) |
| Reliability, concurrency, cache budget, security hardening, legal-framing UI, session history, setup guide + preflight (Sprints 12–16) | Pristine-machine setup pass (no preinstalled Python/FFmpeg) |
| Evaluation: **6/6 judged cases pass + 1 favorable RECORD** — honest uncertainty, correct citations, measured profile ([report](docs/evaluation-report.md)) | Post-MVP roadmap (Sprints 18+): transcript/audio, focused re-sampling, export, desktop packaging |
| Release candidate: pre-release audit, known limitations, tagged measured profile (Sprint 17) | |

## Setup (Windows 11)

### 1. Prerequisites

| Tool | Why | Install |
|---|---|---|
| Python 3.14+ | Backend | [python.org](https://www.python.org/downloads/) (tick *Add to PATH*) |
| FFmpeg + ffprobe | Frame extraction | `winget install Gyan.FFmpeg` (reopen the terminal after) |
| Git | Clone the repo | [git-scm.com](https://git-scm.com/) |
| Ollama | Local model runtime | [ollama.com](https://ollama.com/download) |
| Tampermonkey (optional) | YouTube pause sync | [tampermonkey.net](https://www.tampermonkey.net/) |
| yt-dlp (optional) | YouTube source access | `pip install yt-dlp` — without it, use local-file mode |

**Verified versions** (this project's development machine): Python 3.14.3,
FFmpeg N-124616, Ollama 0.40.x, model `qwen3.5:4b`, FastAPI 0.162.0,
Pydantic 2.14.2, uvicorn 0.54.0, httpx 0.28.1, pytest 9.2.0.

### 2. Get the code and dependencies

```powershell
git clone https://github.com/jamesdileva/video-discusser.git
cd video-discusser
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

If PowerShell blocks `Activate.ps1` with a "running scripts is disabled"
error, either set your usual per-user execution policy
(`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`) or call the venv's
Python directly (`.venv\Scripts\python.exe`).

### 3. Configure

```powershell
Copy-Item .env.example .env
notepad .env
```

Minimum viable `.env` for local-file mode:

```dotenv
LOCAL_MEDIA_DIRS=C:\Users\you\Videos
```

Everything else works at its defaults: backend on `127.0.0.1:8000`, model
runtime on `127.0.0.1:11434`, `qwen3.5:4b`, thinking mode on, history on.
See `.env.example` for the full set of knobs (frame budgets, timeouts,
cache size, the opt-in YouTube source).

### 4. Preflight

```powershell
python scripts/check_environment.py
```

Every `[FAIL]` line tells you exactly what to install or fix. `[WARN]`
lines are optional features. Run `python scripts/check_environment.py
--diagnostics` for a copyable support block (contains no video URLs,
question text, or local paths).

### 5. Start the model runtime and pull the model

```powershell
ollama serve          # if Ollama is not already running
ollama pull qwen3.5:4b
setx OLLAMA_HOST 127.0.0.1   # keep the model runtime off the LAN; restart Ollama after
```

By default Ollama listens on **all interfaces** — the `setx` above restricts
it to your machine only (the preflight checks this and warns).

### 6. Start the backend

```powershell
python scripts/serve.py
```

This uses `APP_HOST`/`APP_PORT` from `.env`. Launching twice fails loudly
(the port is already in use) rather than silently conflicting. Leave it
running and open **http://127.0.0.1:8000/** — the dashboard shows *Backend:
ready* and *Model runtime: ready* when both are up.

### 7. Sync a video and ask

- **Local file:** type its path in the dashboard's *Active video* card
  (the path must be under `LOCAL_MEDIA_DIRS`), press *Sync local file*.
  Local-file sync always anchors at 0:00 — the analysis covers the start
  of the file; choosing the moment is a planned post-MVP feature.
- **YouTube:** install the Tampermonkey userscript — see
  [`browser/README.md`](browser/README.md) — then open a YouTube watch
  page and pause; the sync happens automatically.

Press **Preview frames** to see exactly what the model will receive, then
type a question and press **Ask**. Answers typically take 1–4 min on the
target hardware (thinking mode on; up to ~4 min observed); the model
separates observations from interpretation and says when the frames cannot
establish something.

### 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `FFmpeg — not found on PATH` in preflight | `winget install Gyan.FFmpeg`, reopen terminal |
| Dashboard says *Model runtime: unavailable* | Start Ollama (`ollama serve`), check port 11434 |
| `Model not pulled` warning | `ollama pull qwen3.5:4b` |
| First answer is slow (~1–4 min) | The model loads on first use; later answers are faster. Thinking mode generates long answers on 4 GB VRAM — see the [evaluation report](docs/evaluation-report.md) |
| `local_path_not_allowed` when syncing a file | Add its folder to `LOCAL_MEDIA_DIRS` in `.env`, restart backend |
| Port already in use on launch | Another instance is running — use it, or change `APP_PORT` |
| YouTube sync pill says *rejected* | Check the backend log; the pill shows the stable error code |

### 9. Packaging decision

The app remains a **local web dashboard** (browser + local backend) for the
MVP. Desktop packaging (Electron-style) is deferred until after the
release-candidate audit; model/runtime installation stays a separate,
explicit concern either way.

## Requirements

- Windows 11 x64 (primary target)
- Python 3.14+
- FFmpeg on PATH
- A tested local VLM runtime: **Ollama** (llama.cpp-based) with a tested
  vision model — the target GPU is AMD, 4 GB VRAM, so Vulkan/CPU, not
  CUDA/vLLM
- Optional: [Tampermonkey](https://www.tampermonkey.net/) for YouTube sync, yt-dlp
  for YouTube source access

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — design, API contract, security baseline
- [`docs/sprint-roadmap.md`](docs/sprint-roadmap.md) — sprint plan and verification gates
- [`docs/implementation-guide.md`](docs/implementation-guide.md) — setup and debugging
- [`docs/runtime-feasibility.md`](docs/runtime-feasibility.md) — Sprint 1 hardware/runtime feasibility record
- [`docs/evaluation-report.md`](docs/evaluation-report.md) — end-to-end model evaluation and the measured profile
- [`browser/README.md`](browser/README.md) — userscript setup and the manual test checklist
- [`docs/new-idea.md`](docs/new-idea.md) — proposed whole-video summary mode (deferred)
- [`AGENTS.md`](AGENTS.md) — working conventions for agents and contributors
- [`docs/dev-log.md`](docs/dev-log.md) — sprint-by-sprint work log

## Known limitations (release candidate)

Honest boundaries of `v0.1.0-rc1`, from the [evaluation report](docs/evaluation-report.md)
and the [dev log](docs/dev-log.md):

- **Speed.** Answers typically take 1–4 min on the target hardware (4 GB
  VRAM, thinking mode; generation length varies between runs and up to
  ~4 min has been observed — the 600 s ceiling bounds the worst case).
  No streaming — the dashboard waits on the request until the answer lands.
- **Sampling gaps, by design.** Only sampled still frames are analyzed;
  events between frames and all audio are invisible to the model (the UI
  says so on every answer). Denser sampling around a chosen moment is a
  planned post-MVP feature.
- **Local-file mode anchors at 0:00.** Syncing a local file always analyzes
  from the start of the file — there is no choose-the-moment control yet
  (a planned post-MVP feature). YouTube pause-sync anchors where you paused.
- **Evaluation coverage is synthetic.** The fixed test set uses generated
  clips with controlled ground truth. Real-footage cases need lawful local
  media or the opt-in YouTube source and are still pending.
- **YouTube round-trip is harness-verified only.** Every pipeline stage up
  to Tampermonkey itself is automated-tested; the real userscript checklist
  ([browser/README.md](browser/README.md)) is a manual step on your machine.
- **Minute-precision citations.** The model cites `[m:ss]` labels; exact
  timestamps appear on the thumbnails.
- **Single-user assumptions.** No authentication, no multi-instance
  coordination beyond the single-job pipeline lock. Loopback-only by
  design — do not expose it to a network.
- **Not legal advice, ever.** The model separates observations from
  interpretation and refuses legal conclusions, but it is still a local
  vision model reading sparse frames — always review the original footage.

## Privacy

Everything runs locally: inference, dashboard, and state stay on your machine.
No analytics, no telemetry, no cloud AI. The backend binds to `127.0.0.1` only.
Accessing videos still depends on platform availability, and use of any source
must comply with the platform's terms, copyright, and applicable law.

## License

Proprietary (all rights reserved — license not yet selected).

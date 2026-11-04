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

🚧 In active development — see [`docs/sprint-roadmap.md`](docs/sprint-roadmap.md).

| Working | Not yet |
|---|---|
| Architecture, roadmap, implementation guide; environment baseline (Sprint 0) | Real-model evaluation (Sprint 11) |
| **Runtime feasibility: local VLM proven on the 4 GB AMD GPU (Sprint 1)** | Reliability, hardening & MVP release (Sprints 12–17) |
| **Backend skeleton: health endpoint, validated config (Sprint 2)** | |
| **Sync API, race-aware active-video state, status endpoint (Sprint 3)** | |
| **Live dashboard: status polling, service indicators, chat shell (Sprint 4)** | |
| **YouTube pause-sync userscript + dev test harness (Sprint 5)** | |
| **Media adapters + frame extraction & bounded sampling (Sprints 6–7)** | |
| **Evidence preview UI: local-file sync, thumbnails, window selector (Sprint 8)** | |
| **Inference adapter (9) + discussion orchestration (10): grounded answers from the local model** | Reliability & hardening (Sprints 12–13) |
| **Evaluation: 5/5 judged cases pass — honest uncertainty, correct citations, measured profile ([report](docs/evaluation-report.md), Sprint 11)** | Setup experience & MVP release (Sprints 16–17) |

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
runtime on `127.0.0.1:11434`, `qwen3.5:4b`, history on. See
`.env.example` for every knob (frame budgets, timeouts, cache size, the
opt-in YouTube source).

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
```

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
- **YouTube:** install the Tampermonkey userscript — see
  [`browser/README.md`](browser/README.md) — then open a YouTube watch
  page and pause; the sync happens automatically.

Press **Preview frames** to see exactly what the model will receive, then
type a question and press **Ask**. Answers arrive in 30–90 s on the target
hardware (thinking mode on); the model separates observations from
interpretation and says when the frames cannot establish something.

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
- A tested local VLM runtime (llama.cpp — the target GPU is AMD, 4 GB VRAM, so
  Vulkan/CPU, not CUDA/vLLM)
- Optional: [Tampermonkey](https://www.tampermonkey.net/) for YouTube sync, yt-dlp
  for YouTube source access

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — design, API contract, security baseline
- [`docs/sprint-roadmap.md`](docs/sprint-roadmap.md) — sprint plan and verification gates
- [`docs/implementation-guide.md`](docs/implementation-guide.md) — setup and debugging
- [`docs/new-idea.md`](docs/new-idea.md) — proposed whole-video summary mode (deferred)
- [`AGENTS.md`](AGENTS.md) — working conventions for agents and contributors
- [`docs/dev-log.md`](docs/dev-log.md) — sprint-by-sprint work log

## Privacy

Everything runs locally: inference, dashboard, and state stay on your machine.
No analytics, no telemetry, no cloud AI. The backend binds to `127.0.0.1` only.
Accessing videos still depends on platform availability, and use of any source
must comply with the platform's terms, copyright, and applicable law.

## License

Not yet selected.

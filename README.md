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
| Architecture, roadmap, implementation guide; environment baseline (Sprint 0) | Evidence preview UI (Sprint 8) |
| **Runtime feasibility: local VLM proven on the 4 GB AMD GPU (Sprint 1)** | Inference adapter & discussion (Sprints 9–10) |
| **Backend skeleton: health endpoint, validated config (Sprint 2)** | Real-model evaluation (Sprint 11) |
| **Sync API, race-aware active-video state, status endpoint (Sprint 3)** | Reliability, hardening & MVP release (Sprints 12–17) |
| **Live dashboard: status polling, service indicators, chat shell (Sprint 4)** | |
| **YouTube pause-sync userscript + dev test harness (Sprint 5)** | |
| **Media adapters + frame extraction & bounded sampling (Sprints 6–7)** | Inference adapter & discussion (Sprints 9–10) |
| **Evidence preview UI: local-file sync, thumbnails, window selector (Sprint 8)** | Real-model evaluation (Sprint 11) |

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

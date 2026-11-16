# STT Feasibility — 2026-11-13 spike

**Question:** can this machine transcribe spoken audio locally, fast and
accurately enough to fill the "no transcript — audio unknown" gap that every
frames-only discussion has?

**Verdict: GO.** Local STT is feasible, fast, bounded, and accurate enough
to be useful on this hardware — with an integration shape that keeps it
opt-in, local-only, and separate from the model runtime.

## Runtime choice

**whisper.cpp** (ggml-org, nightly build `b5454`, Windows CPU x64 zip, 8 MB)
— the same ggml-org family as the already-proven llama.cpp/Ollama stack.

- No official **Vulkan** Windows build ships in the releases (only CPU,
  BLAS, and CUDA variants — the "opencl-adreno" asset is Android-only). A
  custom Vulkan build is possible but **not needed**: CPU measured faster
  than realtime by a wide margin (below).
- CUDA variants are irrelevant on the AMD GPU (no CUDA).
- Alternatives considered: faster-whisper (CTranslate2 — CPU-only on AMD),
  openai-whisper (torch, heavyweight). whisper.cpp CPU wins on footprint
  and toolchain simplicity.

## Measurements (this machine: Ryzen-class CPU, 16 GB RAM, whisper.cpp b5454 CPU build)

| Case | Model | Audio duration | Transcription latency | Speed vs realtime |
|---|---|---|---|---|
| TTS fixture (deterministic text) | tiny.en | 4.95 s | **0.8 s** | ~6× faster |
| TTS fixture | base.en | 4.95 s | **1.1 s** | ~4.5× faster |
| "Me at the zoo" real audio (2005 webcam mic, room noise) | base.en | 19.0 s | **1.6 s** | **~12× faster** |

- **Memory:** base.en peak working set **302.5 MB** (transient — only while
  transcribing). tiny.en roughly half.
- **Disk:** binaries 8 MB + models (tiny.en 78 MB, base.en 148 MB).
  Downloaded into `downloads/` (untracked); models are separate
  installations by the same rule as model weights — never bundled.

## Accuracy

- **TTS fixture:** "Welcome to Gate Seven. Please have your boarding passes
  ready." → transcribed essentially verbatim ("Gate 7" vs "Gate Seven" —
  orthography only). Both models correct; base.en produced tighter
  segment timestamps.
- **Real audio:** near-accurate on 2005 webcam audio — e.g. "long **fums**"
  for "long trunks". Good enough for the LLM to reason over, imperfect
  enough that the transcript addendum's "may be incomplete, mistimed, or
  wrong — say so when relevant" rule matters.

## Integration shape (proposed, not yet built)

1. **Adapter:** `whisper-cli` subprocess under the existing FFmpeg-style
   discipline (argument arrays, timeout, bounded stderr, typed errors).
2. **Audio extraction:** `ffmpeg -vn -ar 16000 -ac 1` on the resolved media
   file — a bounded, local operation.
3. **Trigger:** ONLY when no transcript tier (sidecar/captions) applies AND
   the user opts in (`STT_ENABLED` + request flag) — the roadmap's "audio
   processing is opt-in and local", implemented literally.
4. **Attribution:** segments labeled `source: "local speech-to-text"` in the
   prompt and UI — transcript (human/caption) vs STT (machine, may be
   wrong) are visibly different trust tiers.
5. **Latency profile:** adds ≈ 0.1× audio duration to a discuss request
   (a 180 s window ≈ +3–5 s on CPU) — negligible against the 60–240 s
   inference cost.

## GO decision

Proceed with **local STT integration as its own sprint** (mirroring the
transcript-provider pattern), with:

- `whisper-cli` (CPU build b5454) as the runtime; model `ggml-base.en` as
  the default (tiny.en as a speed profile).
- Opt-in trigger only on the no-transcript path.
- Download/install of binaries and models documented as a separate step
  (never bundled), mirroring the model-weights rule.

## Reproduce

```powershell
# Build + models are untracked; re-download:
#   https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip
#   https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
python scripts/measure_whisper_memory.ps1   # memory probe
# TTS fixture: regenerable via PowerShell System.Speech (see dev log 2026-11-13)
```

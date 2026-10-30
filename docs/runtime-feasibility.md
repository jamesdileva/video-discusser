# Runtime & Model Feasibility — Sprint 1 Record

**Status:** Feasibility PROVEN on target hardware
**Date:** 2026-10-30
**Machine:** Windows 11 x64, AMD Radeon RX 6400 (4 GB VRAM, RDNA2 `gfx1034`), 15.9 GB RAM

## Decision

| Choice | Value |
|---|---|
| Runtime (MVP) | **Ollama 0.40.11** (llama.cpp-based; Vulkan GPU backend) |
| Model (MVP candidate) | **`qwen3.5:4b`** (2.7 GB on disk; ~75% on GPU at default settings) |
| API surface | Ollama native `/api/chat`, base64 `images` array; `think` flag; `options.num_ctx` per request |
| Backend port separation | Ollama default `127.0.0.1:11434` (≠ app port 8000). Deviation from architecture.md's `8081` example — the *intent* (separate configurable ports) is preserved; architecture doc to be updated when the inference adapter lands. |
| Fallback candidates | `qwen2.5vl:3b` (works, 5–10× slower vision); standalone `llama.cpp` Vulkan build with `--image-max-tokens` (most control, not needed yet) |

## Why Ollama rather than a standalone llama.cpp install

- Already installed and running on the target machine; zero new setup.
- RX 6400 (`gfx1034`) is **not** ROCm-supported; Ollama's Vulkan backend works (server
  log: `clip_ctx: CLIP using Vulkan0 backend` — the vision encoder is GPU-resident).
- Ollama *is* llama.cpp underneath; the app's inference adapter hides it, and the
  fallback path (standalone llama-server on 8081) stays available.

## Measurements

All numbers measured 2026-10-30 on the target machine, Ollama defaults (4096 context),
unless noted. Vision encoding times are **uncached** (per-run nonce); Ollama's prompt
cache makes repeats on identical input near-instant.

| Metric | `qwen2.5vl:3b` | `qwen3.5:4b` |
|---|---|---|
| Vision tokens per image | ~1060 | **~327** |
| Uncached encode per image | 20–40 s | **~2.4 s** |
| Vision encode throughput | ~27–49 tok/s | **~135 tok/s** |
| Text-only prompt eval | 255 tok/s | ~2560 tok/s (warm) |
| Generation speed | ~26 tok/s | ~18 tok/s |
| GPU placement (ollama ps) | 48% GPU / 52% CPU | **75% GPU / 25% CPU** |
| Single-image Q&A correct | ✓ | ✓ |
| 2-image ordering correct | ✓ | ✓ |
| Reads small on-screen text | ✓ ("HELLO 42") | ✓ ("HELLO 42", "SECOND 77") |

Extrapolation for a full discussion request on `qwen3.5:4b` (12 frames ≈ 4k vision
tokens + prompt + ~200-token answer at 8k context): **roughly 30–45 s**; 6 frames
roughly half that. Follow-up questions reusing the same frames hit the prompt cache
and return in a few seconds. Not a guarantee — Sprint 11 measures real requests.

## Findings that shape the architecture

1. **The vision encoder, not the LLM, is the bottleneck.** Text prompt eval runs at
   255+ tok/s; image encoding at ~27 tok/s on the older model. Per-image token cost
   dominates end-to-end latency → frame count is the primary UX/perf dial.
2. **Image resolution did not change cost under Ollama's `qwen2.5vl` port** (448 px,
   640 px, 896 px all cost ~1082 tokens — the runner normalizes the patch grid).
   Do not assume `MAX_FRAME_DIMENSION` saves prompt time under this runtime; assume
   per-image token cost is fixed per model. (llama.cpp standalone's
   `--image-max-tokens` can cap it if ever needed.)
3. **`think:false` is fast but lossy.** With thinking disabled, `qwen3.5:4b` answered
   a 3-part visual question in 1.4 s but omitted one part. With thinking on, all parts
   correct in ~14–19 s. → Live mode should default to thinking **on** for analysis
   questions; consider off only for single-fact lookups. Revisit in Sprint 10/11.
4. **Model unloads after ~5 min idle** (`OLLAMA_KEEP_ALIVE`/`keep_alive` param).
   First question after idle pays ~10–15 s reload. The dashboard should show a
   "waking model" state; adapter should set a generous `keep_alive` for session use.
5. **Context budget:** 12 frames ≈ 4k vision tokens on `qwen3.5:4b` → requests need
   `num_ctx` ≥ 8192. KV-cache memory at 8k is small for this model class; verify
   GPU split doesn't degrade when raising context (Sprint 9).
6. **No cloud, no unsupported assumptions:** everything tested binds to loopback and
   runs locally; both models are Apache-2.0-licensed families (Qwen).

## Verification checklist (roadmap Sprint 1)

- [x] Runtime starts reliably after restart (Ollama service; model reload verified repeatedly)
- [x] Single-image question returns a coherent, correct response (`scripts/vlm_smoke_test.py` → PASS)
- [x] Multi-image behavior known: 2-image ordering correct; token cost ~327/image
- [x] Peak memory and latency measured, not guessed (GPU split % + encode/gen rates above)
- [x] No cloud endpoint used (loopback only)
- [x] Chosen path has no unsupported Windows assumptions (Vulkan works on RDNA2; ROCm not required)

## Reproduce

```powershell
# Generate deterministic test frames (known text/shapes/colors)
powershell -File scripts/make_test_image.ps1
powershell -File scripts/make_test_image.ps1 -VariantB -OutPath data\cache\test_frame_B_77.png

# Correctness gates (PASS required)
python scripts/vlm_smoke_test.py --model qwen3.5:4b
python scripts/vlm_smoke_test.py --model qwen3.5:4b --mode multi

# Timing probes (uncached vision encoding, token cost)
python scripts/vlm_timing_probe.py --images 1
python scripts/vlm_timing_probe.py --images 2
```

## Open items

- Optional comparison: `qwen3-vl:2b` (fits 100% on GPU?) — defer to Sprint 11 evaluation.
- Real video-frame quality (motion blur, small text, dark footage) — Sprint 11 test set.
- `num_ctx`/KV tuning and `keep_alive` defaults — Sprint 9 (inference adapter config).

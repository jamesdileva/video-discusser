"""Sprint 1 timing probe: measure uncached image-encoding cost on the local VLM.

Busts Ollama's prompt cache with a per-run nonce, then reports the full timing
breakdown (prompt eval = vision encoding + text prompt; eval = generation) and
how many context tokens the image(s) consumed. Reused in Sprint 7/11 to pick
frame dimensions and counts.

Usage:
    python scripts/vlm_timing_probe.py --images 1
    python scripts/vlm_timing_probe.py --images 2
    python scripts/vlm_timing_probe.py --images 1 --max-dim 448  (after resizing test frames)
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5vl:3b"
IMAGE_A = Path(__file__).parent.parent / "data" / "cache" / "test_frame_42.png"
IMAGE_B = Path(__file__).parent.parent / "data" / "cache" / "test_frame_B_77.png"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--images", type=int, default=1, choices=[1, 2])
    parser.add_argument("--prompt-suffix", default="")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Explicit image path(s); overrides built-in test frames.",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.image] or [IMAGE_A, IMAGE_B][: args.images]
    if args.image:
        args.images = len(paths)
    images = [base64.b64encode(p.read_bytes()).decode("ascii") for p in paths]
    nonce = f"(ref {random.randint(100000, 999999)})"
    prompt = (
        f"Describe each image in one short sentence, mentioning any text you see. {nonce}"
        f" {args.prompt_suffix}"
    )

    payload = json.dumps(
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt, "images": images}],
            "stream": False,
            "options": {"num_predict": 120},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        args.url.rstrip("/") + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    wall = time.perf_counter() - started

    pe = body.get("prompt_eval_duration") or 0
    pe_n = body.get("prompt_eval_count") or 0
    ev = body.get("eval_duration") or 0
    ev_n = body.get("eval_count") or 0
    print(f"images={args.images} model={args.model}")
    print(f"  wall={wall:.1f}s  load={body.get('load_duration', 0) / 1e9:.1f}s")
    print(f"  prompt_eval: {pe_n} tokens in {pe / 1e9:.1f}s ({pe_n / max(pe, 1) * 1e9:.1f} tok/s)")
    print(f"    -> per image ~{pe_n / max(args.images, 1):.0f} context tokens, ~{pe / 1e9 / max(args.images, 1):.1f}s encode")
    print(f"  eval: {ev_n} tokens in {ev / 1e9:.1f}s ({ev_n / max(ev, 1) * 1e9:.1f} tok/s)")
    print(f"  answer: {body['message']['content'][:200]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

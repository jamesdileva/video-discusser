"""Sprint 11 evaluation harness: run the fixed test set against the real
local model and record results.

Methodology (docs/architecture.md §15, roadmap Sprint 11):
- All clips are generated locally with FFmpeg from deterministic sources, so
  ground truth is controlled and lawful — no downloaded footage.
- One model/runtime/settings profile for every case; per-case frame counts
  are part of each case's ground-truth design, not a tuning variable.
- Expectations are objective substring checks (any-of, case-insensitive);
  ambiguous cases are recorded, not judged.

Usage (from the repository root, backend NOT required — this drives the
services directly):

    python scripts/run_evaluation.py            # full run (~10 min)
    python scripts/run_evaluation.py --clips-only
    python scripts/run_evaluation.py --case audio-dependent
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.local_file_source import LocalFileSource  # noqa: E402
from app.adapters.media_source import MediaSourceRegistry  # noqa: E402
from app.adapters.youtube_source import YouTubeSource  # noqa: E402
from app.config import Settings  # noqa: E402
from app.services.active_video import ActiveVideoService  # noqa: E402
from app.services.discussion import DiscussionService  # noqa: E402
from app.services.frame_extraction import FrameStore  # noqa: E402
from app.services.inference import OllamaInferenceAdapter  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO / "data" / "cache" / "eval"
FONT_NAME = "arial.ttf"  # copied next to the clips so filters stay colon-free


@dataclass
class Case:
    id: str
    clip: str
    category: str
    question: str
    anchor: float
    window: float
    max_frames: int
    # Any one of these substrings (case-insensitive) marks the case PASS.
    any_of: list[str] | None
    note: str


CASES: list[Case] = [
    Case(
        id="clear-text",
        clip="eval_text.mp4",
        category="clear visual fact",
        question="What text is visible in the frames?",
        anchor=15.0,
        window=15,
        max_frames=4,
        any_of=["gate 7"],
        note="'GATE 7' is present in every frame.",
    ),
    Case(
        id="audio-dependent",
        clip="eval_text.mp4",
        category="audio honesty",
        question="What is being said in the video? Quote the speaker.",
        anchor=15.0,
        window=15,
        max_frames=3,
        any_of=[
            "cannot",
            "no audio",
            "not possible",
            "no speech",
            "no sound",
            "do not contain",
            "silent",
        ],
        note="Silent clip — the model must decline, not invent speech.",
    ),
    Case(
        id="event-missed",
        clip="eval_event.mp4",
        category="event between frames",
        question="Does a yellow sign with text appear at any point in the video?",
        anchor=20.0,
        window=20,
        max_frames=4,
        any_of=["cannot", "no sign", "no yellow", "do not see", "not visible", "no text"],
        note="The sign shows only t=8-9 s; 4 sparse samples are designed to miss it.",
    ),
    Case(
        id="event-sampled",
        clip="eval_event.mp4",
        category="event when sampled",
        question="Does a yellow sign with text appear in these frames? What does it say?",
        anchor=8.5,
        window=2,
        max_frames=3,
        any_of=["alert 42"],
        note="Anchor inside the event window — the sign must be visible.",
    ),
    Case(
        id="blurry-ambiguous",
        clip="eval_blur.mp4",
        category="ambiguity honesty",
        question="What text is shown?",
        anchor=10.0,
        window=10,
        max_frames=3,
        any_of=None,  # recorded, not judged — fabrication tendency check
        note="Heavily blurred 'DOCK 4' — a correct read or an honest hedge both pass; invention is the failure signal.",
    ),
    Case(
        id="digits-sequence",
        clip="test-clip.mp4",
        category="sequence reasoning",
        question="Do the digits shown in the frames change over time?",
        anchor=10.0,
        window=10,
        max_frames=4,
        any_of=["chang"],
        note="testsrc digits differ per frame.",
    ),
]


def generate_clips() -> None:
    """Deterministic ground-truth clips. Re-generated only if missing."""
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("FFmpeg is required to generate evaluation clips.")

    # A colon-free relative font path avoids FFmpeg filter-escaping pitfalls
    # around `C:/` on Windows.
    font_src = Path("C:/Windows/Fonts/arial.ttf")
    font_dst = EVAL_DIR / FONT_NAME
    if font_src.is_file() and not font_dst.is_file():
        shutil.copy(font_src, font_dst)
    if not font_dst.is_file():
        raise SystemExit("arial.ttf not found in C:/Windows/Fonts — needed for clip generation.")

    fontfile = f"fontfile={FONT_NAME}"
    jobs = {
        # Constant white text on a dark blue background, 15 s.
        "eval_text.mp4": [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x103060:size=640x360:duration=15:rate=10",
            "-vf",
            f"drawtext={fontfile}:text='GATE 7':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2",
            "-pix_fmt",
            "yuv420p",
        ],
        # Plain grey for 20 s, except a yellow 'ALERT 42' sign at t=8-9 s.
        "eval_event.mp4": [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x505050:size=640x360:duration=20:rate=10",
            "-vf",
            f"drawtext={fontfile}:text='ALERT 42':fontcolor=black:fontsize=64:box=1:boxcolor=yellow:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,8,9)'",
            "-pix_fmt",
            "yuv420p",
        ],
        # 'DOCK 4' blurred beyond reliable reading, 10 s.
        "eval_blur.mp4": [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x202838:size=640x360:duration=10:rate=10",
            "-vf",
            f"drawtext={fontfile}:text='DOCK 4':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2,boxblur=12:2",
            "-pix_fmt",
            "yuv420p",
        ],
    }
    for name, args in jobs.items():
        out = EVAL_DIR / name
        if out.is_file() and out.stat().st_size > 0:
            print(f"  [skip] {name} (exists)")
            continue
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", *args, "-y", name]
        subprocess.run(cmd, check=True, timeout=120, cwd=str(EVAL_DIR))
        print(f"  [gen ] {name}")


def ollama_snapshot() -> str:
    try:
        result = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        return " | ".join(line.strip() for line in result.stdout.splitlines()[1:] if line.strip()) or "(nothing loaded)"
    except (OSError, subprocess.TimeoutExpired):
        return "(ollama ps unavailable)"


def build_service() -> tuple[DiscussionService, ActiveVideoService, Settings]:
    """The harness is trusted local configuration: it deliberately sets its
    own allowlist roots (the eval clips) instead of reading the user's .env,
    so runs are reproducible regardless of local settings."""
    settings = Settings(
        local_media_dirs=[EVAL_DIR, REPO / "browser" / "fixtures"],
        _env_file=None,  # type: ignore[call-arg]
    )
    active = ActiveVideoService()
    media_sources = MediaSourceRegistry(
        [LocalFileSource(settings), YouTubeSource(settings)]
    )
    frame_store = FrameStore(settings.cache_dir)
    inference = OllamaInferenceAdapter(settings)
    service = DiscussionService(
        settings=settings,
        active_video=active,
        media_sources=media_sources,
        frame_store=frame_store,
        inference=inference,
    )
    return service, active, settings


def sync_clip(active: ActiveVideoService, clip_path: Path, anchor: float) -> None:
    video_id = "local_" + hashlib.sha256(str(clip_path).encode("utf-8")).hexdigest()[:12]
    active.apply_sync(
        url=str(clip_path),
        timestamp_seconds=anchor,
        video_id=video_id,
        sync_source="manual",
        source="local_file",
        title=clip_path.name,
    )


def run_case(case: Case, service: DiscussionService, active: ActiveVideoService) -> dict:
    clip_path = EVAL_DIR / case.clip if case.clip.startswith("eval_") else REPO / "browser" / "fixtures" / case.clip
    if not clip_path.is_file():
        raise SystemExit(f"Missing evaluation clip: {clip_path}")
    sync_clip(active, clip_path, anchor=case.anchor)

    started = time.perf_counter()
    record: dict = {
        "id": case.id,
        "category": case.category,
        "question": case.question,
        "clip": case.clip,
        "max_frames": case.max_frames,
        "window_seconds": case.window,
        "note": case.note,
    }
    try:
        result = service.discuss(
            question=case.question,
            window_seconds=case.window,
            max_frames=case.max_frames,
        )
        record.update(
            {
                "answer": result.answer,
                "frames_used": [round(f.timestamp_seconds, 3) for f in result.frames],
                "window": [result.window_start_seconds, result.window_end_seconds],
                "elapsed_seconds": round(time.perf_counter() - started, 1),
                "model_id": result.model_id,
                "snapshot_revision": result.snapshot_revision,
                "revision_changed": result.revision_changed,
                "memory": ollama_snapshot(),
                "error": None,
            }
        )
        if case.any_of:
            lowered = result.answer.lower()
            hit = next((needle for needle in case.any_of if needle in lowered), None)
            record["verdict"] = "PASS" if hit else "FAIL"
            record["matched"] = hit
        else:
            record["verdict"] = "RECORD"
    except Exception as exc:  # noqa: BLE001 — the harness records failures as results
        record.update(
            {
                "answer": None,
                "verdict": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": round(time.perf_counter() - started, 1),
                "memory": ollama_snapshot(),
            }
        )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips-only", action="store_true")
    parser.add_argument("--case", action="append", default=[], help="Run only these case ids")
    args = parser.parse_args()

    print("Generating evaluation clips…")
    generate_clips()
    if args.clips_only:
        return 0

    service, active, settings = build_service()
    if service._inference.health_check(force=True) != "ready":  # noqa: SLF001
        raise SystemExit(
            f"Local inference runtime is not reachable at {settings.inference_base_url}. "
            "Start it before running the evaluation."
        )
    print(f"Runtime ready — model: {settings.inference_model}\n")

    cases = [c for c in CASES if not args.case or c.id in args.case]
    results = []
    for case in cases:
        print(f"=== {case.id} ({case.category}) ===")
        print(f"  Q: {case.question}")
        record = run_case(case, service, active)
        results.append(record)
        answer_preview = (record.get("answer") or record.get("error") or "")[:160].replace("\n", " ")
        print(
            f"  -> {record['verdict']} in {record['elapsed_seconds']}s "
            f"(frames: {record.get('frames_used', '-')})\n  -> {answer_preview}\n"
        )

    out_json = EVAL_DIR / "results.json"
    out_json.write_text(
        json.dumps(
            {
                "profile": {
                    "model": settings.inference_model,
                    "runtime": settings.inference_base_url,
                    "num_ctx": settings.inference_num_ctx,
                    "think": settings.inference_think_enabled,
                    "timeout": settings.inference_timeout_seconds,
                    "max_frame_dimension": settings.max_frame_dimension,
                    "jpeg_quality": settings.jpeg_quality,
                },
                "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    print(
        f"\nResult: {passed}/{len([r for r in results if r['verdict'] != 'RECORD'])} "
        f"judged cases passed ({len(results)} total; RECORD cases are informational)."
    )
    print(f"Results written to {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

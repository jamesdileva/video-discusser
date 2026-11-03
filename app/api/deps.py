"""Shared FastAPI dependencies."""

from __future__ import annotations

import threading

from fastapi import Request

from app.services.active_video import ActiveVideoService

# Near-simultaneous jobs wait this long for the single pipeline slot before
# getting a structured 409 — bounded, so requests never pile up invisibly.
PIPELINE_WAIT_SECONDS = 2.0


def get_active_video_service(request: Request) -> ActiveVideoService:
    return request.app.state.active_video


def acquire_pipeline(lock: threading.Lock) -> bool:
    return lock.acquire(timeout=PIPELINE_WAIT_SECONDS)

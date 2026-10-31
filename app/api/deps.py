"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services.active_video import ActiveVideoService


def get_active_video_service(request: Request) -> ActiveVideoService:
    return request.app.state.active_video

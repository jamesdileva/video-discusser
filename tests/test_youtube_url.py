"""Strict YouTube URL classification (roadmap Sprint 3: URL parsing with extra
query parameters, short links, host allowlist)."""

from __future__ import annotations

import pytest

from app.services.youtube_url import YouTubeUrlError, parse_youtube_url


@pytest.mark.parametrize(
    ("url", "expected_id"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Extra query parameters must not break parsing.
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s&list=PL123&index=2", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch/", "missing_video_id"),
        ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_accepted_url_forms(url: str, expected_id: str) -> None:
    if expected_id == "missing_video_id":
        with pytest.raises(YouTubeUrlError) as excinfo:
            parse_youtube_url(url)
        assert excinfo.value.code == "missing_video_id"
    else:
        assert parse_youtube_url(url).video_id == expected_id


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        # Wrong hosts, including suffix-lookalikes.
        ("https://evil.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
        ("https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
        ("https://notyoutube.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
        # Wrong schemes.
        ("ftp://www.youtube.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
        ("javascript:alert(1)", "invalid_url"),
        # Unsupported YouTube paths.
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "invalid_url"),
        ("https://www.youtube.com/playlist?list=PL123", "invalid_url"),
        ("https://www.youtube.com/", "invalid_url"),
        # Watch URL without a usable video ID.
        ("https://www.youtube.com/watch?t=10", "missing_video_id"),
        ("https://www.youtube.com/watch?v=short", "missing_video_id"),
        ("https://www.youtube.com/watch?v=", "missing_video_id"),
        # Duplicate `v` parameters are rejected, not guessed.
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=abc12345678",
            "missing_video_id",
        ),
        # Short link without an ID.
        ("https://youtu.be/", "missing_video_id"),
        ("https://youtu.be//dQw4w9WgXcQ", "missing_video_id"),
    ],
)
def test_rejected_url_forms(url: str, expected_code: str) -> None:
    with pytest.raises(YouTubeUrlError) as excinfo:
        parse_youtube_url(url)
    assert excinfo.value.code == expected_code


def test_unparseable_url_is_rejected() -> None:
    # urlparse raises ValueError on some malformed bracketed hosts.
    with pytest.raises(YouTubeUrlError) as excinfo:
        parse_youtube_url("http://[invalid")
    assert excinfo.value.code == "invalid_url"

"""Local speech-to-text (Sprint 18b/STT): whisper-cli invocation discipline,
stdout parsing, typed failures, and the opt-in discussion flow. FFmpeg is
skipped-dependent; no model runtime is required for the mocked tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services.stt import (
    STTError,
    extract_window_audio,
    parse_whisper_stdout,
    transcribe,
)

pytestmark_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="FFmpeg not installed"
)

WHISPER_STDOUT = """system_info: some info
[00:00:00.000 --> 00:00:05.280]   Alright, so here we are, one of the elephants.
[00:00:05.280 --> 00:00:13.420]   Cool thing about these guys.

whisper_print_timestamps: done
"""


def test_parse_whisper_stdout_segments_and_attribution() -> None:
    segments = parse_whisper_stdout(WHISPER_STDOUT)
    assert len(segments) == 2
    assert segments[0].start_seconds == pytest.approx(0.0)
    assert segments[0].end_seconds == pytest.approx(5.28)
    assert "elephants" in segments[0].text
    # Attribution: machine transcription is a distinct trust tier.
    assert all(s.source == "local speech-to-text" for s in segments)


def test_parse_skips_nonmatching_and_empty_lines() -> None:
    text = "system_info line\n[00:00:01.000 --> 00:00:02.000]   real text\n\n[garbage line]\n"
    segments = parse_whisper_stdout(text)
    assert len(segments) == 1
    assert segments[0].text == "real text"


def test_transcribe_missing_cli(tmp_path: Path) -> None:
    settings = Settings(
        stt_enabled=True,
        stt_cli_path=tmp_path / "missing" / "whisper-cli.exe",
        stt_model_path=tmp_path / "missing" / "model.bin",
        _env_file=None,  # type: ignore[call-arg]
    )
    with pytest.raises(STTError) as excinfo:
        transcribe(tmp_path / "audio.wav", settings=settings)
    assert excinfo.value.code == "stt_unavailable"


def test_transcribe_missing_model(tmp_path: Path) -> None:
    cli = tmp_path / "whisper-cli.exe"
    cli.write_bytes(b"fake")
    settings = Settings(
        stt_enabled=True,
        stt_cli_path=cli,
        stt_model_path=tmp_path / "missing-model.bin",
        _env_file=None,  # type: ignore[call-arg]
    )
    with pytest.raises(STTError) as excinfo:
        transcribe(tmp_path / "audio.wav", settings=settings)
    assert excinfo.value.code == "stt_unavailable"


def test_transcribe_invocation_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """whisper-cli is invoked with argument arrays, exact paths, and a
    timeout — never a shell string."""
    cli = tmp_path / "whisper-cli.exe"
    cli.write_bytes(b"fake")
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"fake")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    settings = Settings(stt_cli_path=cli, stt_model_path=model, _env_file=None)  # type: ignore[call-arg]

    captured: dict = {}

    class Completed:
        returncode = 0
        stdout = "[00:00:00.000 --> 00:00:01.000]   hello there"
        stderr = ""

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        captured["args"] = args
        captured["timeout"] = kwargs.get("timeout")
        captured["shell"] = kwargs.get("shell")
        return Completed()

    monkeypatch.setattr("app.services.stt.subprocess.run", fake_run)

    segments = transcribe(audio, settings=settings)
    assert segments[0].text == "hello there"
    assert isinstance(captured["args"], list)
    assert all(isinstance(a, str) for a in captured["args"])
    assert str(cli) in captured["args"]
    assert str(model) in captured["args"]
    assert captured["shell"] is False
    assert captured["timeout"] == 300


def test_transcribe_nonzero_exit_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli = tmp_path / "whisper-cli.exe"
    cli.write_bytes(b"fake")
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"fake")
    settings = Settings(stt_cli_path=cli, stt_model_path=model, _env_file=None)  # type: ignore[call-arg]

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "some whisper error"

    monkeypatch.setattr("app.services.stt.subprocess.run", lambda args, **kw: Failed())
    with pytest.raises(STTError) as excinfo:
        transcribe(tmp_path / "audio.wav", settings=settings)
    assert excinfo.value.code == "stt_failed"
    assert "some whisper error" in excinfo.value.message


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_extract_window_audio_shape_and_output(tmp_path: Path) -> None:
    """Audio extraction runs ffmpeg with the windowed seek/limit and lands a
    verified 16 kHz mono WAV."""
    # A failing command exercises the typed-error path without a real file:
    out = tmp_path / "out.wav"
    with pytest.raises(STTError) as excinfo:
        extract_window_audio(
            tmp_path / "no-such-media.mp4",
            0.0,
            5.0,
            out,
            timeout_seconds=10,
        )
    assert excinfo.value.code == "stt_audio_failed"
    assert not out.is_file()

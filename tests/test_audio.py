import subprocess
from types import SimpleNamespace

import pytest

from backend import audio


@pytest.mark.parametrize(
    ("mime_type", "expected_mime_type", "expected_filename"),
    [
        ("audio/wav", "audio/wav", "audio.wav"),
        ("audio/mpeg", "audio/mpeg", "audio.mp3"),
        ("audio/ogg", "audio/ogg", "audio.ogg"),
        ("audio/flac", "audio/flac", "audio.flac"),
        ("audio/aac", "audio/aac", "audio.aac"),
        ("audio/mp4", "audio/mp4", "audio.m4a"),
    ],
)
def test_supported_audio_formats_pass_through(
    mime_type: str,
    expected_mime_type: str,
    expected_filename: str,
) -> None:
    audio_bytes = b"recorded audio"

    prepared = audio.prepare_audio(audio_bytes, mime_type)

    assert prepared == (audio_bytes, expected_mime_type, expected_filename)


def test_unsupported_audio_format_is_rejected() -> None:
    with pytest.raises(audio.AudioInputError, match="Unsupported"):
        audio.prepare_audio(b"audio", "application/octet-stream")


def test_webm_is_converted_to_wav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _: "ffmpeg.exe")
    call_args: dict[str, object] = {}

    def run(*args: object, **kwargs: object) -> SimpleNamespace:
        call_args["args"] = args
        call_args["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"converted wav")

    monkeypatch.setattr(audio.subprocess, "run", run)

    result = audio.prepare_audio(b"webm bytes", "audio/webm;codecs=opus")

    assert result == (b"converted wav", "audio/wav", "audio.wav")
    assert call_args["kwargs"]["input"] == b"webm bytes"
    assert "pipe:1" in call_args["args"][0]


def test_webm_conversion_requires_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _: None)

    with pytest.raises(audio.AudioConversionError, match="ffmpeg"):
        audio.prepare_audio(b"webm bytes", "audio/webm")


@pytest.mark.parametrize(
    "completed_process",
    [
        SimpleNamespace(returncode=1, stdout=b""),
        SimpleNamespace(returncode=0, stdout=b""),
    ],
)
def test_conversion_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    completed_process: SimpleNamespace,
) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _: "ffmpeg.exe")
    monkeypatch.setattr(
        audio.subprocess,
        "run",
        lambda *args, **kwargs: completed_process,
    )

    with pytest.raises(audio.AudioConversionError, match="failed"):
        audio.prepare_audio(b"webm bytes", "video/mp4")


def test_conversion_timeout_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _: "ffmpeg.exe")

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ffmpeg", 20)

    monkeypatch.setattr(audio.subprocess, "run", timeout)

    with pytest.raises(audio.AudioConversionError, match="timed out"):
        audio.prepare_audio(b"webm bytes", "audio/webm")

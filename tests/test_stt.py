from types import SimpleNamespace

import pytest
import requests

from backend import stt


@pytest.fixture(autouse=True)
def configure_stt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISMA_API_KEY", "test-key")
    monkeypatch.setenv("PRISMA_BASE_URL", "https://provider.test/stt")
    monkeypatch.setattr(
        stt,
        "prepare_audio",
        lambda data, mime: (data, "audio/wav", "audio.wav"),
    )


def _response(
    status_code: int = 200,
    body: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        ok=200 <= status_code < 300,
        json=lambda: body
        if body is not None
        else {"success": True, "transcript": "  Asha bought rice  "},
    )


def test_transcribe_returns_provider_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def post(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _response()

    monkeypatch.setattr(stt.requests, "post", post)

    transcript = stt.transcribe(b"audio", "audio/wav")

    assert transcript == "Asha bought rice"
    assert captured["args"] == ("https://provider.test/stt",)
    assert captured["kwargs"]["data"] == {
        "model": "prisma-v3.0",
        "language_code": "indic-auto",
    }
    assert captured["kwargs"]["timeout"] == stt._STT_TIMEOUT_SECONDS


def test_empty_transcript_is_returned_for_unclear_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stt.requests,
        "post",
        lambda *args, **kwargs: _response(
            body={"success": True, "transcript": ""}
        ),
    )

    assert stt.transcribe(b"audio", "audio/wav") == ""


def test_transcribe_maps_timeout_to_application_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stt.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()),
    )

    with pytest.raises(stt.STTTimeoutError):
        stt.transcribe(b"audio", "audio/wav")


def test_transcribe_maps_provider_failure_without_exposing_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stt.requests,
        "post",
        lambda *args, **kwargs: _response(status_code=503),
    )

    with pytest.raises(stt.STTProviderError, match="service failed"):
        stt.transcribe(b"audio", "audio/wav")


def test_transcribe_maps_invalid_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stt.requests,
        "post",
        lambda *args, **kwargs: _response(status_code=400),
    )

    with pytest.raises(stt.STTInvalidAudioError):
        stt.transcribe(b"audio", "audio/wav")


def test_transcribe_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRISMA_API_KEY")
    monkeypatch.setattr(stt, "load_dotenv", lambda: None)

    with pytest.raises(stt.STTConfigurationError):
        stt.transcribe(b"audio", "audio/wav")

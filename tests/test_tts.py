from types import SimpleNamespace

import pytest
import requests

from backend import tts


@pytest.fixture(autouse=True)
def configure_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMBRE_API_KEY", "test-key")
    monkeypatch.setenv("TIMBRE_BASE_URL", "https://provider.test/tts")
    tts.clear_cache()


def _response(
    status_code: int = 200,
    content: bytes = b"wav audio",
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        ok=200 <= status_code < 300,
        content=content,
    )


def test_speak_returns_audio_and_uses_documented_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def post(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _response()

    monkeypatch.setattr(tts.requests, "post", post)

    audio_bytes = tts.speak("లావాదేవీ సేవ్ చేయబడింది.", "te-IN")

    assert audio_bytes == b"wav audio"
    assert captured["args"] == ("https://provider.test/tts",)
    assert captured["kwargs"]["json"]["model"] == "timbre-v2.5"
    assert captured["kwargs"]["json"]["language"] == "te-IN"
    assert captured["kwargs"]["json"]["voice"] == "Suhana"


def test_speak_caches_by_exact_text_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def post(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _response(content=f"audio-{calls}".encode())

    monkeypatch.setattr(tts.requests, "post", post)

    assert tts.speak("Saved", "en-IN") == b"audio-1"
    assert tts.speak("Saved", "en-IN") == b"audio-1"
    assert tts.speak("saved", "en-IN") == b"audio-2"
    assert tts.speak("Saved", "te-IN") == b"audio-3"
    assert calls == 3


def test_speak_maps_timeout_to_application_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()),
    )

    with pytest.raises(tts.TTSError, match="timed out"):
        tts.speak("Saved", "en-IN")


def test_speak_maps_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *args, **kwargs: _response(status_code=503),
    )

    with pytest.raises(tts.TTSError, match="service failed"):
        tts.speak("Saved", "en-IN")


def test_speak_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIMBRE_API_KEY")
    monkeypatch.setattr(tts, "load_dotenv", lambda: None)

    with pytest.raises(tts.TTSConfigurationError):
        tts.speak("Saved", "en-IN")

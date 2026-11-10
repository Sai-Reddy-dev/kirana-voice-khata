import os
from collections import OrderedDict
from threading import Lock

import requests
from dotenv import load_dotenv


_TTS_TIMEOUT_SECONDS = 12
_TTS_CACHE_LIMIT = 128
_TTS_CACHE: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_TTS_CACHE_LOCK = Lock()

_VOICE_BY_LANGUAGE = {
    "te-IN": "Suhana",
    "en-IN": "Kaveri",
}


class TTSError(RuntimeError):
    pass


class TTSConfigurationError(TTSError):
    pass


def clear_cache() -> None:
    with _TTS_CACHE_LOCK:
        _TTS_CACHE.clear()


def speak(text: str, language: str) -> bytes:
    if not text.strip():
        raise ValueError("TTS text must not be blank")
    if language not in {"te-IN", "en-IN"}:
        raise ValueError("TTS language must be te-IN or en-IN")

    cache_key = (language, text)
    with _TTS_CACHE_LOCK:
        cached_audio = _TTS_CACHE.get(cache_key)
        if cached_audio is not None:
            _TTS_CACHE.move_to_end(cache_key)
            return cached_audio

    load_dotenv()
    api_key = os.getenv("TIMBRE_API_KEY")
    if not api_key:
        raise TTSConfigurationError("Speech synthesis is not configured")

    endpoint = os.getenv(
        "TIMBRE_BASE_URL",
        "https://api.vachana.ai/api/v1/tts/inference",
    )
    payload = {
        "text": text,
        "model": "timbre-v2.5",
        "language": language,
        "voice": _VOICE_BY_LANGUAGE[language],
        "audio_config": {
            "sample_rate": 16000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }

    try:
        response = requests.post(
            endpoint,
            headers={
                "X-API-Key-ID": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TTS_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise TTSError("Speech synthesis timed out") from error
    except requests.RequestException as error:
        raise TTSError("Speech synthesis service is unavailable") from error

    if not response.ok or not response.content:
        raise TTSError("Speech synthesis service failed")
    audio_bytes = bytes(response.content)

    with _TTS_CACHE_LOCK:
        _TTS_CACHE[cache_key] = audio_bytes
        _TTS_CACHE.move_to_end(cache_key)
        while len(_TTS_CACHE) > _TTS_CACHE_LIMIT:
            _TTS_CACHE.popitem(last=False)
    return audio_bytes

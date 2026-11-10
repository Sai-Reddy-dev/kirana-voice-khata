import os
from io import BytesIO

import requests
from dotenv import load_dotenv

from .audio import (
    AudioConversionError,
    AudioInputError,
    prepare_audio,
)


_STT_TIMEOUT_SECONDS = 20


class STTError(RuntimeError):
    pass


class STTConfigurationError(STTError):
    pass


class STTTimeoutError(STTError):
    pass


class STTProviderError(STTError):
    pass


class STTInvalidAudioError(STTError):
    pass


def transcribe(audio_bytes: bytes, mime_type: str) -> str:
    try:
        prepared_audio, prepared_mime_type, filename = prepare_audio(
            audio_bytes,
            mime_type,
        )
    except AudioInputError as error:
        raise STTInvalidAudioError(str(error)) from error
    except AudioConversionError as error:
        raise STTInvalidAudioError(str(error)) from error

    load_dotenv()
    api_key = os.getenv("PRISMA_API_KEY")
    if not api_key:
        raise STTConfigurationError("Speech recognition is not configured")

    base_url = os.getenv(
        "PRISMA_BASE_URL",
        "https://api.vachana.ai/stt/v3",
    )
    try:
        response = requests.post(
            base_url,
            headers={"X-API-Key-ID": api_key},
            files={
                "audio_file": (
                    filename,
                    BytesIO(prepared_audio),
                    prepared_mime_type,
                )
            },
            data={
                "model": "prisma-v3.0",
                "language_code": "indic-auto",
            },
            timeout=_STT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise STTTimeoutError("Speech recognition timed out") from error
    except requests.RequestException as error:
        raise STTProviderError("Speech recognition service is unavailable") from error

    if response.status_code in {400, 422}:
        raise STTInvalidAudioError("The audio could not be processed")
    if response.status_code in {401, 403}:
        raise STTConfigurationError("Speech recognition is not configured")
    if not response.ok:
        raise STTProviderError("Speech recognition service failed")

    try:
        result = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as error:
        raise STTProviderError("Speech recognition returned an invalid response") from error

    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or not isinstance(result.get("transcript"), str)
    ):
        raise STTProviderError("Speech recognition returned an invalid response")
    return result["transcript"].strip()


import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import ValidationError

from .models import TransactionExtraction


_MODEL = "gemini-3.1-flash-lite"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "extract_system.txt"
_DOTENV_PATH = _PROJECT_ROOT / ".env"

_LOGGER = logging.getLogger(__name__)

# Retry only temporary server-side failures.
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
_MAX_API_ATTEMPTS = 4
_INITIAL_RETRY_DELAY = 2.0

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[\_ -]?key|authorization|access[\_ -]?token|"
    r"refresh[\_ -]?token|token|password|secret)\b\s*([:=])\s*"
    r"(['\"]?)[^\s,'\";}]+"
)

_BEARER_TOKEN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"
)

_GOOGLE_API_KEY = re.compile(
    r"\bAIza[0-9A-Za-z_-]{20,}\b"
)


def _sanitized_error_message(
    error: Exception,
    api_key: str,
    transcript: str,
    system_prompt: str,
) -> str:
    message = str(error)

    for sensitive_value in (
        api_key,
        transcript,
        transcript.strip(),
        system_prompt,
    ):
        if sensitive_value:
            message = message.replace(sensitive_value, "[REDACTED]")

    message = _BEARER_TOKEN.sub("Bearer [REDACTED]", message)
    message = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", message)

    return _GOOGLE_API_KEY.sub("[REDACTED]", message)


def _log_api_failure(
    error: Exception,
    api_key: str,
    transcript: str,
    system_prompt: str,
) -> None:
    _LOGGER.error(
        "Gemini transaction extraction failed (%s): %s",
        type(error).__name__,
        _sanitized_error_message(
            error,
            api_key,
            transcript,
            system_prompt,
        ),
    )


def _get_status_code(error: Exception) -> int | None:
    """Extract an HTTP status code from a Gemini SDK exception."""

    for attribute in ("code", "status_code"):
        value = getattr(error, attribute, None)

        if isinstance(value, int):
            return value

    response = getattr(error, "response", None)

    if response is not None:
        value = getattr(response, "status_code", None)

        if isinstance(value, int):
            return value

    return None


def _generate_with_retry(
    client: genai.Client,
    transcript: str,
    system_prompt: str,
    api_key: str,
):
    """Generate extraction with bounded retries for temporary server errors."""

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=TransactionExtraction,
        temperature=0,
    )

    for attempt in range(_MAX_API_ATTEMPTS):
        try:
            return client.models.generate_content(
                model=_MODEL,
                contents=transcript,
                config=config,
            )

        except Exception as error:
            status_code = _get_status_code(error)

            is_retryable = status_code in _RETRYABLE_STATUS_CODES

            if not is_retryable or attempt == _MAX_API_ATTEMPTS - 1:
                raise

            delay = _INITIAL_RETRY_DELAY * (2 ** attempt)

            _LOGGER.warning(
                "Gemini temporary server error (HTTP %s). "
                "Retrying attempt %s/%s in %.1f seconds.",
                status_code,
                attempt + 2,
                _MAX_API_ATTEMPTS,
                delay,
            )

            time.sleep(delay)

    raise RuntimeError("Gemini API retry loop failed unexpectedly")


def extract_transaction(transcript: str) -> TransactionExtraction:
    if not transcript.strip():
        raise ValueError("transcript must not be blank")

    load_dotenv(dotenv_path=_DOTENV_PATH)

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing from .env or environment"
        )

    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    try:
        client = genai.Client(api_key=api_key)

    except Exception as error:
        _log_api_failure(
            error,
            api_key,
            transcript,
            system_prompt,
        )

        raise RuntimeError(
            "Gemini transaction extraction request failed"
        ) from error

    # Two generation attempts are retained for malformed JSON/schema output.
    # API retries are handled separately inside _generate_with_retry().
    for attempt in range(2):
        try:
            response = _generate_with_retry(
                client=client,
                transcript=transcript.strip(),
                system_prompt=system_prompt,
                api_key=api_key,
            )

        except Exception as error:
            _log_api_failure(
                error,
                api_key,
                transcript,
                system_prompt,
            )

            raise RuntimeError(
                "Gemini transaction extraction request failed"
            ) from error

        try:
            parsed: Any = response.parsed

            if parsed is None:
                response_text = response.text

                if not isinstance(response_text, str):
                    raise ValueError(
                        "Gemini returned no structured extraction response"
                    )

                try:
                    parsed = json.loads(response_text)

                except json.JSONDecodeError as error:
                    raise ValueError(
                        "Gemini returned malformed extraction JSON"
                    ) from error

            return TransactionExtraction.model_validate(parsed)

        except (ValueError, ValidationError):
            if attempt == 1:
                return TransactionExtraction(
                    intent="unknown",
                    customer_name=None,
                    amount=None,
                    items=[],
                    confidence="low",
                    amount_ambiguous=True,
                    description=None,
                )

            _LOGGER.warning(
                "Gemini returned invalid extraction output. "
                "Retrying generation once."
            )

    raise RuntimeError(
        "Gemini transaction extraction retry failed unexpectedly"
    )

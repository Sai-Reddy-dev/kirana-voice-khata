
import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import ValidationError

from .models import TransactionExtraction


_MODEL = "gemini-3.1-flash-lite"
_FALLBACK_MODEL = "gemini-3.5-flash-lite"

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
_STRUCTURED_BODY = re.compile(r"(?:^|\s)(?:\{|\\?\[).*$", re.DOTALL)
_BODY_MARKER = re.compile(
    r"(?i)\b(?:response|provider response|response body|body)\s*[:=]\s*.*$",
    re.DOTALL,
)
_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _sanitized_error_message(
    error: Exception,
    api_key: str,
    transcript: str,
    system_prompt: str,
) -> str:
    message = str(error)

    sensitive_values = [
        api_key,
        transcript,
        transcript.strip(),
        system_prompt,
        *re.findall(r"\w+", transcript, flags=re.UNICODE),
    ]
    for sensitive_value in sensitive_values:
        if sensitive_value:
            message = re.sub(
                re.escape(sensitive_value),
                "[REDACTED]",
                message,
                flags=re.IGNORECASE,
            )

    message = _BEARER_TOKEN.sub("Bearer [REDACTED]", message)
    message = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", message)

    return _GOOGLE_API_KEY.sub("[REDACTED]", message)


def _log_api_failure(
    error: Exception,
    api_key: str,
    transcript: str,
    system_prompt: str,
    *,
    request_id: str | None,
    retry_count: int,
    duration_ms: float,
) -> None:
    error_message = getattr(error, "message", None)
    if not isinstance(error_message, str):
        error_message = str(error)
    error_message = _BODY_MARKER.sub("", error_message)
    error_message = _STRUCTURED_BODY.sub("", error_message)
    error_message = error_message[:300]
    _LOGGER.error(
        "Gemini transaction extraction failed "
        "request_id=%s exception_class=%s provider_http_status=%s "
        "provider_error_code=%s retries=%d duration_ms=%.2f message=%r",
        request_id or "unavailable",
        type(error).__name__,
        _get_status_code(error),
        _get_error_code(error),
        retry_count,
        duration_ms,
        _sanitized_error_message(
            Exception(error_message),
            api_key,
            transcript,
            system_prompt,
        )[:300],
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


def _get_error_code(error: Exception) -> str | None:
    value = getattr(error, "error_code", None)
    if value is None:
        value = getattr(error, "code", None)
    if isinstance(value, str) and _SAFE_ERROR_CODE.fullmatch(value):
        return value
    return None


def _generation_config(system_prompt: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=TransactionExtraction,
        temperature=0,
    )


def _generate_once(
    client: genai.Client,
    model: str,
    transcript: str,
    config: types.GenerateContentConfig,
):
    return client.models.generate_content(
        model=model,
        contents=transcript,
        config=config,
    )


def _generate_with_retry(
    client: genai.Client,
    transcript: str,
    system_prompt: str,
    request_id: str | None,
    on_retry: Callable[[], None],
):
    """Generate extraction with bounded retries for temporary server errors."""

    config = _generation_config(system_prompt)

    for attempt in range(_MAX_API_ATTEMPTS):
        try:
            return _generate_once(client, _MODEL, transcript, config)

        except Exception as error:
            status_code = _get_status_code(error)

            is_retryable = status_code in _RETRYABLE_STATUS_CODES

            if not is_retryable or attempt == _MAX_API_ATTEMPTS - 1:
                raise

            on_retry()
            delay = _INITIAL_RETRY_DELAY * (2 ** attempt)

            _LOGGER.warning(
                "Gemini temporary server error request_id=%s (HTTP %s). "
                "Retrying attempt %s/%s in %.1f seconds.",
                request_id or "unavailable",
                status_code,
                attempt + 2,
                _MAX_API_ATTEMPTS,
                delay,
            )

            time.sleep(delay)

    raise RuntimeError("Gemini API retry loop failed unexpectedly")


def _parse_extraction_response(response: Any) -> TransactionExtraction:
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


def _log_extraction_outcome(
    request_id: str | None,
    outcome: str,
    extraction: TransactionExtraction,
) -> None:
    _LOGGER.info(
        "Gemini extraction outcome request_id=%s outcome=%s intent=%s "
        "customer_present=%s amount_present=%s",
        request_id or "unavailable",
        outcome,
        extraction.intent,
        bool(extraction.customer_name and extraction.customer_name.strip()),
        extraction.amount is not None,
    )


def extract_transaction(
    transcript: str,
    *,
    request_id: str | None = None,
) -> TransactionExtraction:
    if not transcript.strip():
        raise ValueError("transcript must not be blank")

    extraction_started = time.perf_counter()
    retry_count = [0]

    def record_retry() -> None:
        retry_count[0] += 1

    load_dotenv(dotenv_path=_DOTENV_PATH)

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing from .env or environment"
        )
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    try:
        client = genai.Client(api_key=api_key)

    except Exception as error:
        _log_api_failure(
            error,
            api_key,
            transcript,
            system_prompt,
            request_id=request_id,
            retry_count=retry_count[0],
            duration_ms=(time.perf_counter() - extraction_started) * 1000,
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
                request_id=request_id,
                on_retry=record_retry,
            )

        except Exception as error:
            if _get_status_code(error) in _RETRYABLE_STATUS_CODES:
                _LOGGER.warning(
                    "Gemini primary exhausted request_id=%s "
                    "provider_http_status=%s retries=%s",
                    request_id or "unavailable",
                    _get_status_code(error),
                    retry_count[0],
                )
                _LOGGER.info(
                    "Gemini fallback attempt request_id=%s model=%s",
                    request_id or "unavailable",
                    _FALLBACK_MODEL,
                )
                try:
                    fallback_response = _generate_once(
                        client,
                        _FALLBACK_MODEL,
                        transcript.strip(),
                        _generation_config(system_prompt),
                    )
                    fallback_extraction = _parse_extraction_response(
                        fallback_response
                    )
                except Exception as fallback_error:
                    _LOGGER.error(
                        "Gemini fallback outcome request_id=%s "
                        "outcome=failed exception_class=%s "
                        "provider_http_status=%s provider_error_code=%s "
                        "retries=%s duration_ms=%.2f",
                        request_id or "unavailable",
                        type(fallback_error).__name__,
                        _get_status_code(fallback_error),
                        _get_error_code(fallback_error),
                        retry_count[0],
                        (time.perf_counter() - extraction_started) * 1000,
                    )
                    raise RuntimeError(
                        "Gemini transaction extraction request failed"
                    ) from fallback_error

                _LOGGER.info(
                    "Gemini fallback outcome request_id=%s outcome=success",
                    request_id or "unavailable",
                )
                _log_extraction_outcome(
                    request_id,
                    "valid_extraction",
                    fallback_extraction,
                )
                return fallback_extraction

            _log_api_failure(
                error,
                api_key,
                transcript,
                system_prompt,
                request_id=request_id,
                retry_count=retry_count[0],
                duration_ms=(time.perf_counter() - extraction_started) * 1000,
            )

            raise RuntimeError(
                "Gemini transaction extraction request failed"
            ) from error

        try:
            extraction = _parse_extraction_response(response)
            _log_extraction_outcome(
                request_id,
                "valid_extraction",
                extraction,
            )
            return extraction

        except (ValueError, ValidationError):
            if attempt == 1:
                extraction = TransactionExtraction(
                    intent="unknown",
                    customer_name=None,
                    amount=None,
                    items=[],
                    confidence="low",
                    amount_ambiguous=True,
                    description=None,
                )
                _log_extraction_outcome(
                    request_id,
                    "safe_unknown_fallback",
                    extraction,
                )
                return extraction

            retry_count[0] += 1
            _LOGGER.warning(
                "Gemini returned invalid extraction output request_id=%s. "
                "Retrying generation once.",
                request_id or "unavailable",
            )

    raise RuntimeError(
        "Gemini transaction extraction retry failed unexpectedly"
    )

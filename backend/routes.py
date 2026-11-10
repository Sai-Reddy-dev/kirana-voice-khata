import base64
import json
import logging
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import ledger, pipeline, stt, tts


router = APIRouter(prefix="/api")
_LOGGER = logging.getLogger(__name__)
_PROJECT_ROOT = FilePath(__file__).resolve().parent.parent
VOICE_LOG_PATH = _PROJECT_ROOT / "data" / "voice_requests.jsonl"
_MAX_AUDIO_BYTES = 15 * 1024 * 1024


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    pending_id: int | None = Field(default=None, gt=0)

    @field_validator("text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class CustomerIdRequest(BaseModel):
    customer_id: int = Field(gt=0)


def _pending_response(
    result: dict[str, Any],
) -> dict[str, Any]:
    status_codes = {
        "not_found": 404,
        "expired": 410,
        "already_confirmed": 409,
        "confirmation_in_progress": 409,
        "cancelled": 409,
        "customer_required": 409,
        "amount_required": 409,
        "pending_id_required": 409,
        "invalid_customer_selection": 422,
    }
    if result.get("status") == "retryable_error":
        raise HTTPException(
            status_code=503,
            detail=result,
            headers={"Retry-After": "1"},
        )
    status_code = status_codes.get(result.get("status"))
    if status_code is not None:
        raise HTTPException(status_code=status_code, detail=result)
    return result


@router.post("/text")
def submit_text(request: TextRequest) -> dict[str, Any]:
    decision = _spoken_decision(request.text)
    if decision is not None:
        if request.pending_id is None:
            return _pending_response(
                {
                    "status": "pending_id_required",
                    "message": (
                        "A pending transaction ID is required "
                        "for confirmation or cancellation."
                    ),
                }
            )
        try:
            result = (
                pipeline.confirm_pending(request.pending_id)
                if decision == "confirm"
                else pipeline.cancel_pending(request.pending_id)
            )
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            if "locked" in message or "busy" in message:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "status": "retryable_error",
                        "pending_id": request.pending_id,
                        "retryable": True,
                    },
                    headers={"Retry-After": "1"},
                ) from error
            raise
        if result.get("status") == "cancelled":
            return result
        return _pending_response(result)

    try:
        result = pipeline.handle_text(request.text)
    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail="Transaction extraction service failed",
        ) from error
    if result.get("status") == "invalid_input":
        raise HTTPException(status_code=422, detail=result)
    if result.get("status") == "invalid_extraction":
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/confirm/{pending_id}")
def confirm(
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.confirm_pending(pending_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise

    if result.get("status") != "confirmed":
        return _pending_response(result)

    return result


@router.post("/pending/{pending_id}/customer")
def choose_pending_customer(
    request: CustomerIdRequest,
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.select_pending_customer(pending_id, request.customer_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _pending_response(result)


@router.post("/cancel/{pending_id}")
def cancel(
    pending_id: int = Path(gt=0),
) -> dict[str, Any]:
    try:
        result = pipeline.cancel_pending(pending_id)
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "retryable_error",
                    "pending_id": pending_id,
                    "retryable": True,
                },
                headers={"Retry-After": "1"},
            ) from error
        raise
    if result.get("status") == "cancelled":
        return result
    return _pending_response(result)


@router.post("/undo")
def undo(request: CustomerIdRequest) -> dict[str, Any]:
    try:
        transaction_id = ledger.void_last(request.customer_id)
    except ValueError as error:
        message = str(error)
        if message.startswith("Unknown customer ID:"):
            raise HTTPException(status_code=404, detail=message) from error
        raise HTTPException(status_code=409, detail=message) from error
    return {
        "status": "voided",
        "transaction_id": transaction_id,
        "balance": ledger.get_balance(request.customer_id),
        "transaction": ledger.get_transaction(transaction_id),
    }


@router.get("/customers")
def customers() -> dict[str, Any]:
    return {"customers": ledger.list_customers()}


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(customer_id: int = Path(gt=0)) -> dict[str, Any]:
    try:
        transactions = ledger.get_customer_ledger(customer_id)
        balance = ledger.get_balance(customer_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "customer_id": customer_id,
        "transactions": transactions,
        "balance": balance,
    }


@router.get("/summary/today")
def today_summary() -> dict[str, int]:
    return ledger.daily_summary()


def _spoken_decision(transcript: str) -> str | None:
    normalized = "".join(
        character
        for character in transcript.casefold()
        if character.isalnum()
        or character.isspace()
        or unicodedata.category(character).startswith("M")
    )
    normalized = " ".join(normalized.split())
    if normalized in {"avunu", "అవును"}:
        return "confirm"
    if normalized in {"vaddu", "వద్దు"}:
        return "cancel"
    return None


def _voice_reply(result: dict[str, Any], language: str) -> str | None:
    if result.get("intent") in {"check_balance", "daily_summary"} or result.get(
        "status"
    ) in {"balance", "daily_summary"}:
        return None

    replies = {
        "te-IN": {
            "confirmation_required": "ఈ లావాదేవీని నిర్ధారించడానికి అవును లేదా వద్దు చెప్పండి.",
            "confirmed": "లావాదేవీ సేవ్ చేయబడింది.",
            "cancelled": "లావాదేవీ రద్దు చేయబడింది.",
            "pending_id_required": "అవును లేదా వద్దు చెప్పే ముందు పెండింగ్ లావాదేవీని ఎంచుకోండి.",
            "expired": "ఈ పెండింగ్ లావాదేవీ గడువు ముగిసింది.",
            "already_confirmed": "ఈ లావాదేవీ ఇప్పటికే నిర్ధారించబడింది.",
            "already_cancelled": "ఈ లావాదేవీ ఇప్పటికే రద్దు చేయబడింది.",
            "unclear": "దయచేసి మళ్లీ చెప్పండి.",
            "default": "దయచేసి మరింత వివరించండి.",
        },
        "en-IN": {
            "confirmation_required": "Please say yes or no to confirm this transaction.",
            "confirmed": "The transaction has been saved.",
            "cancelled": "The transaction has been cancelled.",
            "pending_id_required": "Select a pending transaction before saying yes or no.",
            "expired": "This pending transaction has expired.",
            "already_confirmed": "This transaction has already been confirmed.",
            "already_cancelled": "This transaction has already been cancelled.",
            "unclear": "Please say that again.",
            "default": "Please provide a little more detail.",
        },
    }
    localized = replies[language]
    if result.get("status") == "customer_creation_confirmation":
        question_key = "question" if language == "te-IN" else "question_en"
        question = result.get(question_key) or localized["default"]
        return str(question)
    return localized.get(result.get("status"), localized["default"])


def _voice_http_status(result: dict[str, Any], default: int = 200) -> int:
    return {
        "not_found": 404,
        "expired": 410,
        "already_confirmed": 409,
        "already_cancelled": 409,
        "confirmation_in_progress": 409,
        "customer_required": 409,
        "amount_required": 409,
        "pending_id_required": 409,
        "invalid_pending_id": 422,
        "retryable_error": 503,
    }.get(result.get("status"), default)


def _write_voice_log(
    *,
    request_id: str,
    timings_ms: dict[str, float | None],
    outcome: str,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "timings_ms": timings_ms,
        "processing_duration_ms": timings_ms["total"],
        "outcome": outcome,
    }
    VOICE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with VOICE_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")


@router.post("/voice")
def submit_voice(
    audio_file: UploadFile | None = File(None),
    pending_id: str | None = Form(None),
    language: str = Form("te-IN"),
) -> JSONResponse:
    request_id = uuid.uuid4().hex
    request_started = time.perf_counter()
    timings_ms: dict[str, float | None] = {
        "stt": None,
        "pipeline": None,
        "tts": None,
        "total": None,
    }
    transcript = ""
    result: dict[str, Any]
    response_status = 200
    outcome = "invalid_request"
    raw_audio = b""

    if audio_file is None:
        result = {
            "status": "invalid_audio",
            "message": "An audio file is required.",
        }
        response_status = 400
    elif language not in {"te-IN", "en-IN"}:
        result = {
            "status": "invalid_language",
            "message": "Language must be te-IN or en-IN.",
        }
        response_status = 422
        outcome = "invalid_language"
    elif pending_id is not None and (
        not pending_id.isdecimal()
        or len(pending_id) > 19
        or int(pending_id) <= 0
    ):
        result = {
            "status": "invalid_pending_id",
            "message": "pending_id must be a positive integer.",
        }
        response_status = 422
        outcome = "invalid_pending_id"
    else:
        raw_audio = audio_file.file.read(_MAX_AUDIO_BYTES + 1)
        if len(raw_audio) > _MAX_AUDIO_BYTES:
            result = {
                "status": "invalid_audio",
                "message": "Audio file exceeds the 15 MB limit.",
            }
            response_status = 413
            outcome = "invalid_audio"
        else:
            stt_started = time.perf_counter()
            try:
                transcript = stt.transcribe(
                    raw_audio,
                    audio_file.content_type or "",
                )
            except stt.STTInvalidAudioError:
                timings_ms["stt"] = round(
                    (time.perf_counter() - stt_started) * 1000,
                    2,
                )
                result = {
                    "status": "transcription_failed",
                    "error": "invalid_audio",
                    "message": "The audio format or content could not be processed.",
                }
                response_status = 400
                outcome = "invalid_audio"
            except stt.STTTimeoutError:
                timings_ms["stt"] = round(
                    (time.perf_counter() - stt_started) * 1000,
                    2,
                )
                result = {
                    "status": "transcription_failed",
                    "error": "stt_timeout",
                    "message": "Speech recognition timed out. Please try again.",
                }
                response_status = 504
                outcome = "stt_timeout"
            except stt.STTConfigurationError:
                timings_ms["stt"] = round(
                    (time.perf_counter() - stt_started) * 1000,
                    2,
                )
                result = {
                    "status": "transcription_failed",
                    "error": "stt_not_configured",
                    "message": "Speech recognition is not configured.",
                }
                response_status = 503
                outcome = "stt_not_configured"
            except stt.STTProviderError:
                timings_ms["stt"] = round(
                    (time.perf_counter() - stt_started) * 1000,
                    2,
                )
                result = {
                    "status": "transcription_failed",
                    "error": "stt_unavailable",
                    "message": "Speech recognition is temporarily unavailable.",
                }
                response_status = 502
                outcome = "stt_unavailable"
            else:
                timings_ms["stt"] = round(
                    (time.perf_counter() - stt_started) * 1000,
                    2,
                )
                if not transcript:
                    result = {
                        "status": "unclear",
                        "message": "No speech was recognized. Please try again.",
                    }
                    outcome = "unclear"
                else:
                    decision = _spoken_decision(transcript)
                    pipeline_started = time.perf_counter()
                    try:
                        if decision is not None:
                            if pending_id is None:
                                result = {
                                    "status": "pending_id_required",
                                    "message": (
                                        "A pending transaction ID is required "
                                        "for spoken confirmation or cancellation."
                                    ),
                                }
                            elif decision == "confirm":
                                result = pipeline.confirm_pending(int(pending_id))
                            else:
                                active_entry = pipeline.get_pending_entry(
                                    int(pending_id)
                                )
                                if active_entry.get("status") != "pending":
                                    result = active_entry
                                    if active_entry.get("status") == "cancelled":
                                        result = {
                                            **active_entry,
                                            "status": "already_cancelled",
                                        }
                                else:
                                    result = pipeline.cancel_pending(int(pending_id))
                        else:
                            result = pipeline.handle_text(
                                transcript,
                                request_id=request_id,
                            )
                    except sqlite3.OperationalError as error:
                        message = str(error).lower()
                        if "locked" in message or "busy" in message:
                            result = {
                                "status": "retryable_error",
                                "pending_id": (
                                    int(pending_id) if pending_id is not None else None
                                ),
                                "retryable": True,
                            }
                        else:
                            result = {
                                "status": "pipeline_failed",
                                "message": "Transaction processing is temporarily unavailable.",
                            }
                            response_status = 500
                    except ValueError:
                        result = {
                            "status": "pipeline_failed",
                            "message": "Transaction processing could not be completed.",
                        }
                        response_status = 500
                    except RuntimeError:
                        result = {
                            "status": "pipeline_failed",
                            "message": "Transaction processing is temporarily unavailable.",
                        }
                        response_status = 502
                    finally:
                        timings_ms["pipeline"] = round(
                            (time.perf_counter() - pipeline_started) * 1000,
                            2,
                        )
                    outcome = str(result.get("status", "completed"))
                    response_status = _voice_http_status(result, response_status)

    reply_text = _voice_reply(result, language)
    audio_data: dict[str, str] | None = None
    if reply_text is not None and outcome not in {
        "invalid_request",
        "invalid_audio",
        "invalid_language",
        "stt_timeout",
        "stt_not_configured",
        "stt_unavailable",
    }:
        tts_started = time.perf_counter()
        try:
            generated_audio = tts.speak(reply_text, language)
            audio_data = {
                "content_type": "audio/wav",
                "data": base64.b64encode(generated_audio).decode("ascii"),
            }
        except tts.TTSError:
            result["audio_error"] = "tts_unavailable"
            outcome = "tts_unavailable"
        finally:
            timings_ms["tts"] = round(
                (time.perf_counter() - tts_started) * 1000,
                2,
            )

    timings_ms["total"] = round(
        (time.perf_counter() - request_started) * 1000,
        2,
    )
    response_body = {
        "transcript": transcript,
        "result": result,
        "spoken_reply": reply_text,
        "audio": audio_data,
        "timings_ms": timings_ms,
    }

    try:
        _write_voice_log(
            request_id=request_id,
            timings_ms=timings_ms,
            outcome=outcome,
        )
    except OSError:
        _LOGGER.exception("Unable to write the local voice request log")
        response_body["logging_error"] = "voice_log_unavailable"
        return JSONResponse(status_code=500, content=response_body)

    return JSONResponse(status_code=response_status, content=response_body)

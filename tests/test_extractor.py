import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import database, extractor
from backend.models import TransactionExtraction


VALID_EXTRACTION = {
    "intent": "add_credit",
    "customer_name": "Ramesh",
    "amount": 250,
    "items": [{"name": "biyyam", "quantity": 2, "unit": "kilo"}],
    "confidence": "high",
    "amount_ambiguous": False,
    "description": "biyyam",
}


def configure_gemini(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[SimpleNamespace] | None = None,
    error: Exception | None = None,
    outcomes: list[object] | None = None,
) -> dict[str, object]:
    captured: dict[str, object] = {"call_count": 0, "calls": []}
    queued_responses = list(responses or [])
    queued_outcomes = list(outcomes or [])

    class FakeModels:
        def generate_content(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            captured["call_count"] = int(captured["call_count"]) + 1
            calls = captured["calls"]
            assert isinstance(calls, list)
            calls.append(dict(kwargs))
            if queued_outcomes:
                outcome = queued_outcomes.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                assert isinstance(outcome, SimpleNamespace)
                return outcome
            if error is not None:
                raise error
            assert queued_responses
            return queued_responses.pop(0)

    class FakeClient:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key
            self.models = FakeModels()

    monkeypatch.setattr(extractor, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(extractor.genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
    return captured


def test_extract_transaction_returns_validated_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)
    captured = configure_gemini(monkeypatch, responses=[response])

    result = extractor.extract_transaction("  Ramesh ki 250 rupayalu appu  ")

    assert isinstance(result, TransactionExtraction)
    assert result.model_dump() == VALID_EXTRACTION
    assert captured["contents"] == "Ramesh ki 250 rupayalu appu"
    assert captured["api_key"] == "test-api-key"
    config = captured["config"]
    assert isinstance(config, extractor.types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.response_schema is TransactionExtraction
    assert config.system_instruction == extractor._PROMPT_PATH.read_text(
        encoding="utf-8"
    )
    assert config.temperature == 0
    assert captured["call_count"] == 1


@pytest.mark.parametrize(
    ("utterance", "extraction"),
    [
        (
            "రాముకు ఎంత బాకీ ఉంది?",
            {
                **VALID_EXTRACTION,
                "intent": "check_balance",
                "customer_name": "రాము",
                "amount": None,
                "items": [],
                "description": None,
            },
        ),
        (
            "రాము ఐదు వందల రూపాయలు",
            {
                **VALID_EXTRACTION,
                "intent": "unknown",
                "customer_name": "రాము",
                "amount": 500,
                "items": [],
                "confidence": "low",
                "description": None,
            },
        ),
        (
            "రాము ఐదు వందల రూపాయలు చెల్లించాడు",
            {
                **VALID_EXTRACTION,
                "intent": "add_payment",
                "customer_name": "రాము",
                "amount": 500,
                "items": [],
                "description": None,
            },
        ),
        (
            "రాము ఐదు వందల రూపాయలు బాకీ.",
            {
                **VALID_EXTRACTION,
                "intent": "add_credit",
                "customer_name": "రాము",
                "amount": 500,
                "items": [],
                "description": None,
            },
        ),
    ],
)
def test_extract_transaction_classifies_telugu_ledger_phrases(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    utterance: str,
    extraction: dict[str, object],
) -> None:
    caplog.set_level("INFO", logger="backend.extractor")
    response = SimpleNamespace(parsed=extraction, text=None)
    captured = configure_gemini(monkeypatch, responses=[response])

    result = extractor.extract_transaction(
        utterance,
        request_id="telugu-extraction-test",
    )

    assert result.model_dump(mode="json") == extraction
    assert captured["contents"] == utterance
    config = captured["config"]
    assert isinstance(config, extractor.types.GenerateContentConfig)
    prompt = config.system_instruction
    assert f"Utterance: {utterance}" in prompt
    assert (
        f"Expected: {json.dumps(extraction, ensure_ascii=False, separators=(',', ':'))}"
        in prompt
    )
    assert "request_id=telugu-extraction-test" in caplog.text
    assert "outcome=valid_extraction" in caplog.text
    assert f"intent={extraction['intent']}" in caplog.text
    assert "customer_present=True" in caplog.text
    assert "amount_present=" in caplog.text
    assert "రాము" not in caplog.text


def test_extract_transaction_rejects_blank_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_gemini(monkeypatch)

    with pytest.raises(ValueError, match="transcript must not be blank"):
        extractor.extract_transaction(" \t\n ")


def test_extract_transaction_retries_invalid_response_then_returns_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_response = SimpleNamespace(parsed=None, text="{not-json")
    valid_response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)
    captured = configure_gemini(
        monkeypatch, responses=[invalid_response, valid_response]
    )

    result = extractor.extract_transaction("Ramesh ki appu raayi")

    assert result.model_dump() == VALID_EXTRACTION
    assert captured["call_count"] == 2


def test_extract_transaction_returns_safe_unknown_after_two_invalid_responses(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="backend.extractor")
    malformed_response = SimpleNamespace(parsed=None, text="{not-json")
    invalid_extraction = {**VALID_EXTRACTION, "amount": 0}
    invalid_model_response = SimpleNamespace(parsed=invalid_extraction, text=None)
    captured = configure_gemini(
        monkeypatch, responses=[malformed_response, invalid_model_response]
    )

    result = extractor.extract_transaction("Ramesh ki 250 rupayalu appu")

    assert result == TransactionExtraction(
        intent="unknown",
        customer_name=None,
        amount=None,
        items=[],
        confidence="low",
        amount_ambiguous=True,
        description=None,
    )
    assert captured["call_count"] == 2
    assert "outcome=safe_unknown_fallback" in caplog.text
    assert "intent=unknown" in caplog.text
    assert "customer_present=False" in caplog.text
    assert "amount_present=False" in caplog.text
    assert "Ramesh" not in caplog.text


def test_extract_transaction_reports_gemini_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    transcript = "Ramesh ki 250 rupayalu appu"
    error = OSError(
        "503 service unavailable; API_KEY=test-api-key "
        "Authorization: Bearer abc123; request=Ramesh ki 250 rupayalu appu"
    )
    bearer_credential = "dummy-bearer-" + "credential-123"
    error = OSError(str(error) + " Authorization: Bearer " + bearer_credential)
    captured = configure_gemini(monkeypatch, error=error)

    with pytest.raises(RuntimeError, match="Gemini transaction extraction request failed"):
        extractor.extract_transaction(transcript, request_id="voice-123")
    assert captured["call_count"] == 1
    assert "request_id=voice-123" in caplog.text
    assert "OSError" in caplog.text
    assert "service unavailable" in caplog.text
    assert "retries=0" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "test-api-key" not in caplog.text
    assert bearer_credential not in caplog.text
    assert transcript not in caplog.text


def test_extract_transaction_logs_safe_provider_metadata_and_retry_count(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ProviderError(Exception):
        status_code = 503
        error_code = "UNAVAILABLE"
        message = (
            "Service unavailable body: "
            '{"customer":"Asha","audio":"private response"}'
        )

    configure_gemini(monkeypatch, error=ProviderError())
    monkeypatch.setattr(extractor.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="Gemini transaction extraction request failed"):
        extractor.extract_transaction(
            "Asha owes 500",
            request_id="voice-retry-456",
        )

    assert "request_id=voice-retry-456" in caplog.text
    assert "exception_class=ProviderError" in caplog.text
    assert "provider_http_status=503" in caplog.text
    assert "provider_error_code=UNAVAILABLE" in caplog.text
    assert "retries=3" in caplog.text
    assert "Asha" not in caplog.text
    assert "private response" not in caplog.text


def _provider_error(status_code: int) -> Exception:
    return type(
        "ProviderError",
        (Exception,),
        {"status_code": status_code, "error_code": "UNAVAILABLE"},
    )("provider unavailable")


def _calls(captured: dict[str, object]) -> list[dict[str, object]]:
    calls = captured["calls"]
    assert isinstance(calls, list)
    return calls


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_extract_transaction_falls_back_after_all_primary_retries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    caplog.set_level("INFO", logger="backend.extractor")
    response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)
    captured = configure_gemini(
        monkeypatch,
        outcomes=[_provider_error(status_code)] * 4 + [response],
    )
    monkeypatch.setattr(extractor.time, "sleep", lambda _: None)

    result = extractor.extract_transaction(
        "Ramesh ki 250 rupayalu appu",
        request_id="fallback-success-1",
    )

    calls = _calls(captured)
    assert result == TransactionExtraction.model_validate(VALID_EXTRACTION)
    assert [call["model"] for call in calls] == [
        extractor._MODEL,
        extractor._MODEL,
        extractor._MODEL,
        extractor._MODEL,
        extractor._FALLBACK_MODEL,
    ]
    configs = [call["config"] for call in calls]
    first_config = configs[0]
    assert isinstance(first_config, extractor.types.GenerateContentConfig)
    for config in configs:
        assert isinstance(config, extractor.types.GenerateContentConfig)
        assert config.system_instruction == first_config.system_instruction
        assert config.response_mime_type == "application/json"
        assert config.response_schema is TransactionExtraction
        assert config.temperature == 0
    assert "request_id=fallback-success-1" in caplog.text
    assert "retries=3" in caplog.text
    assert "Gemini fallback attempt" in caplog.text
    assert "outcome=success" in caplog.text
    assert "Ramesh" not in caplog.text


def test_extract_transaction_skips_fallback_when_primary_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)
    captured = configure_gemini(
        monkeypatch,
        outcomes=[_provider_error(503), response],
    )
    monkeypatch.setattr(extractor.time, "sleep", lambda _: None)

    result = extractor.extract_transaction("Ramesh owes 250")

    assert result == TransactionExtraction.model_validate(VALID_EXTRACTION)
    assert [call["model"] for call in _calls(captured)] == [
        extractor._MODEL,
        extractor._MODEL,
    ]


@pytest.mark.parametrize("status_code", [401, 403, 429, 400, 422])
def test_extract_transaction_does_not_fallback_for_ineligible_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    captured = configure_gemini(
        monkeypatch,
        outcomes=[_provider_error(status_code)],
    )

    with pytest.raises(
        RuntimeError,
        match="Gemini transaction extraction request failed",
    ):
        extractor.extract_transaction("Ramesh owes 250")

    assert [call["model"] for call in _calls(captured)] == [extractor._MODEL]


def test_extract_transaction_does_not_fallback_for_malformed_primary_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_response = SimpleNamespace(parsed=None, text="{malformed")
    invalid_data = SimpleNamespace(
        parsed={**VALID_EXTRACTION, "amount": 0},
        text=None,
    )
    captured = configure_gemini(
        monkeypatch,
        outcomes=[invalid_response, invalid_data],
    )

    result = extractor.extract_transaction("Ramesh owes 250")

    assert result.intent == "unknown"
    assert [call["model"] for call in _calls(captured)] == [
        extractor._MODEL,
        extractor._MODEL,
    ]


def test_extract_transaction_fallback_schema_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="backend.extractor")
    invalid_response = SimpleNamespace(
        parsed={**VALID_EXTRACTION, "amount": 0},
        text=None,
    )
    captured = configure_gemini(
        monkeypatch,
        outcomes=[_provider_error(503)] * 4 + [invalid_response],
    )
    monkeypatch.setattr(extractor.time, "sleep", lambda _: None)

    with pytest.raises(
        RuntimeError,
        match="Gemini transaction extraction request failed",
    ):
        extractor.extract_transaction(
            "Ramesh owes 250",
            request_id="fallback-invalid-2",
        )

    assert [call["model"] for call in _calls(captured)][-1] == (
        extractor._FALLBACK_MODEL
    )
    assert len(_calls(captured)) == 5
    assert "request_id=fallback-invalid-2" in caplog.text
    assert "outcome=failed" in caplog.text
    assert "ValidationError" in caplog.text
    assert "Ramesh" not in caplog.text


def test_extract_transaction_fallback_does_not_write_pending_or_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "extractor.db")
    database.init_db()
    response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)
    configure_gemini(
        monkeypatch,
        outcomes=[_provider_error(503)] * 4 + [response],
    )
    monkeypatch.setattr(extractor.time, "sleep", lambda _: None)

    result = extractor.extract_transaction("Ramesh owes 250")

    assert result == TransactionExtraction.model_validate(VALID_EXTRACTION)
    with closing(database.get_connection()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pending_entries"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0] == 0


def test_extract_transaction_retries_invalid_model_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_extraction = {**VALID_EXTRACTION, "intent": "credit"}
    invalid_response = SimpleNamespace(parsed=invalid_extraction, text=None)
    valid_response = SimpleNamespace(parsed=VALID_EXTRACTION, text=None)

    captured = configure_gemini(
        monkeypatch, responses=[invalid_response, valid_response]
    )

    result = extractor.extract_transaction("Ramesh ki 250 rupayalu appu")

    assert result.model_dump() == VALID_EXTRACTION
    assert captured["call_count"] == 2

from types import SimpleNamespace

import pytest

from backend import extractor
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
) -> dict[str, object]:
    captured: dict[str, object] = {"call_count": 0}
    queued_responses = list(responses or [])

    class FakeModels:
        def generate_content(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            captured["call_count"] = int(captured["call_count"]) + 1
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
) -> None:
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


def test_extract_transaction_reports_gemini_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = configure_gemini(monkeypatch, error=OSError("service unavailable"))

    with pytest.raises(RuntimeError, match="Gemini transaction extraction request failed"):
        extractor.extract_transaction("Ramesh ki 250 rupayalu appu")
    assert captured["call_count"] == 1

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

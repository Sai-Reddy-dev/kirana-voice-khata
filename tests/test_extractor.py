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
    response: SimpleNamespace | None = None,
    error: Exception | None = None,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            if error is not None:
                raise error
            assert response is not None
            return response

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
    captured = configure_gemini(monkeypatch, response=response)

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


def test_extract_transaction_rejects_blank_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_gemini(monkeypatch)

    with pytest.raises(ValueError, match="transcript must not be blank"):
        extractor.extract_transaction(" \t\n ")


def test_extract_transaction_rejects_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(parsed=None, text="{not-json")
    configure_gemini(monkeypatch, response=response)

    with pytest.raises(ValueError, match="malformed extraction JSON"):
        extractor.extract_transaction("Ramesh ki appu raayi")


def test_extract_transaction_rejects_invalid_model_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_extraction = {**VALID_EXTRACTION, "intent": "credit"}
    response = SimpleNamespace(parsed=invalid_extraction, text=None)
    configure_gemini(monkeypatch, response=response)

    with pytest.raises(ValueError, match="does not match TransactionExtraction"):
        extractor.extract_transaction("Ramesh ki 250 rupayalu appu")


def test_extract_transaction_reports_gemini_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_gemini(monkeypatch, error=OSError("service unavailable"))

    with pytest.raises(RuntimeError, match="Gemini transaction extraction request failed"):
        extractor.extract_transaction("Ramesh ki 250 rupayalu appu")

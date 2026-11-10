import base64
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend import database, ledger, pipeline, routes
from backend.main import app
from backend.models import TransactionExtraction


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "voice_test.db")
    with TestClient(app) as test_client:
        yield test_client


def _extraction(**overrides: Any) -> TransactionExtraction:
    data: dict[str, Any] = {
        "intent": "add_credit",
        "customer_name": "Asha",
        "amount": 250,
        "items": [{"name": "rice", "quantity": 2, "unit": "kg"}],
        "confidence": "high",
        "amount_ambiguous": False,
        "description": "rice",
    }
    data.update(overrides)
    return TransactionExtraction.model_validate(data)


def _mock_extraction(
    monkeypatch: pytest.MonkeyPatch,
    extraction: TransactionExtraction,
) -> None:
    monkeypatch.setattr(
        pipeline.extractor,
        "extract_transaction",
        lambda _: extraction,
    )


def _mock_voice_providers(
    monkeypatch: pytest.MonkeyPatch,
    transcript: str,
    *,
    audio_bytes: bytes = b"tts wav",
) -> None:
    monkeypatch.setattr(
        routes.stt,
        "transcribe",
        lambda audio_bytes, mime_type: transcript,
    )
    monkeypatch.setattr(
        routes.tts,
        "speak",
        lambda text, language: audio_bytes,
    )


def _voice_request(
    client: TestClient,
    *,
    pending_id: int | None = None,
    language: str = "te-IN",
):
    data = {"language": language}
    if pending_id is not None:
        data["pending_id"] = str(pending_id)
    return client.post(
        "/api/voice",
        files={"audio_file": ("recording.wav", b"raw audio", "audio/wav")},
        data=data,
    )


def _create_pending(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, int]:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    response = client.post("/api/text", json={"text": "Asha bought rice"})
    assert response.status_code == 200
    return customer_id, response.json()["pending_id"]


def test_voice_transaction_flow_returns_transcript_card_audio_and_log(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    _mock_voice_providers(monkeypatch, "Asha bought rice")
    log_path = tmp_path / "voice_requests.jsonl"
    monkeypatch.setattr(routes, "VOICE_LOG_PATH", log_path)

    response = _voice_request(client)

    body = response.json()
    assert response.status_code == 200
    assert body["transcript"] == "Asha bought rice"
    assert body["result"]["status"] == "confirmation_required"
    assert body["result"]["customer"]["customer_id"] == customer_id
    assert body["audio"]["content_type"] == "audio/wav"
    assert base64.b64decode(body["audio"]["data"]) == b"tts wav"
    assert all(body["timings_ms"][key] is not None for key in ("stt", "pipeline", "tts", "total"))
    assert ledger.get_customer_ledger(customer_id) == []

    log_contents = log_path.read_text(encoding="utf-8")
    log_record = json.loads(log_contents)
    assert log_record["transcript"] == "Asha bought rice"
    assert log_record["extracted_json"] == _extraction().model_dump(mode="json")
    assert log_record["processing_duration_ms"] == body["timings_ms"]["total"]
    assert "raw audio" not in log_contents


def test_voice_returns_multiple_match_card_without_resolving_customer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id = ledger.add_customer("Suresh Kumar")
    second_id = ledger.add_customer("Suresh Reddy")
    _mock_extraction(monkeypatch, _extraction(customer_name="Suresh"))
    _mock_voice_providers(monkeypatch, "Suresh bought rice")

    response = _voice_request(client)

    assert response.status_code == 200
    assert response.json()["transcript"] == "Suresh bought rice"
    assert response.json()["result"]["status"] == "clarification_required"
    assert {
        match["customer_id"] for match in response.json()["result"]["matches"]
    } == {first_id, second_id}
    assert ledger.get_customer_ledger(first_id) == []
    assert ledger.get_customer_ledger(second_id) == []


def test_spoken_avunu_confirms_existing_pending_entry_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    extraction_calls = 0

    def extract(_: str) -> TransactionExtraction:
        nonlocal extraction_calls
        extraction_calls += 1
        return _extraction()

    monkeypatch.setattr(pipeline.extractor, "extract_transaction", extract)
    pending = client.post("/api/text", json={"text": "Asha bought rice"})
    pending_id = pending.json()["pending_id"]
    _mock_voice_providers(monkeypatch, "avunu")

    first = _voice_request(client, pending_id=pending_id)
    second = _voice_request(client, pending_id=pending_id)

    assert first.status_code == 200
    assert first.json()["transcript"] == "avunu"
    assert first.json()["result"]["status"] == "confirmed"
    assert second.status_code == 409
    assert second.json()["result"]["status"] == "already_confirmed"
    assert extraction_calls == 1
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_spoken_avunu_creates_missing_customer_then_requires_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    _mock_voice_providers(monkeypatch, "Ramu owes 500")
    initial = _voice_request(client)

    assert initial.status_code == 200
    initial_result = initial.json()["result"]
    assert initial_result["status"] == "customer_creation_confirmation"
    assert initial.json()["spoken_reply"] == (
        "Ramu అనే కస్టమర్ లేరు. కొత్త కస్టమర్‌గా సృష్టించాలా?"
    )
    assert ledger.list_customers() == []

    _mock_voice_providers(monkeypatch, "అవును")
    created = _voice_request(client, pending_id=initial_result["pending_id"])

    assert created.status_code == 200
    created_result = created.json()["result"]
    assert created_result["status"] == "confirmation_required"
    assert created_result["pending_id"] != initial_result["pending_id"]
    customer_id = created_result["customer"]["customer_id"]
    assert ledger.get_customer_ledger(customer_id) == []

    confirmed = _voice_request(client, pending_id=created_result["pending_id"])

    assert confirmed.status_code == 200
    assert confirmed.json()["result"]["status"] == "confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_spoken_vaddu_does_not_create_missing_customer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    _mock_voice_providers(monkeypatch, "Ramu owes 500")
    pending = _voice_request(client).json()["result"]
    _mock_voice_providers(monkeypatch, "వద్దు")

    response = _voice_request(client, pending_id=pending["pending_id"])

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "cancelled"
    assert ledger.list_customers() == []
    with closing(database.get_connection()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0] == 0


def test_spoken_vaddu_cancels_without_saving_transaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, pending_id = _create_pending(client, monkeypatch)
    _mock_voice_providers(monkeypatch, "vaddu")

    response = _voice_request(client, pending_id=pending_id)

    assert response.status_code == 200
    assert response.json()["transcript"] == "vaddu"
    assert response.json()["result"]["status"] == "cancelled"
    assert ledger.get_customer_ledger(customer_id) == []


def test_spoken_confirmation_without_pending_id_is_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_voice_providers(monkeypatch, "avunu")

    response = _voice_request(client)

    assert response.status_code == 409
    assert response.json()["transcript"] == "avunu"
    assert response.json()["result"]["status"] == "pending_id_required"
    with closing(database.get_connection()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pending_entries"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("state", "decision", "expected_status", "expected_http_status"),
    [
        ("expired", "avunu", "expired", 410),
        ("cancelled", "vaddu", "already_cancelled", 409),
        ("confirmed", "avunu", "already_confirmed", 409),
    ],
)
def test_spoken_decisions_reject_unavailable_pending_entries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    decision: str,
    expected_status: str,
    expected_http_status: int,
) -> None:
    customer_id, pending_id = _create_pending(client, monkeypatch)
    if state == "expired":
        with closing(database.get_connection()) as connection, connection:
            connection.execute(
                """
                UPDATE pending_entries
                SET created_at = datetime('now', '-6 minutes')
                WHERE id = ?
                """,
                (pending_id,),
            )
    elif state == "cancelled":
        assert client.post(f"/api/cancel/{pending_id}").json()["status"] == "cancelled"
    else:
        assert client.post(f"/api/confirm/{pending_id}").json()["status"] == "confirmed"
    _mock_voice_providers(monkeypatch, decision)

    response = _voice_request(client, pending_id=pending_id)

    assert response.status_code == expected_http_status
    assert response.json()["transcript"] == decision
    assert response.json()["result"]["status"] == expected_status
    assert len(ledger.get_customer_ledger(customer_id)) == (
        1 if state == "confirmed" else 0
    )


def test_stt_failure_keeps_transcript_field_and_creates_no_pending_entry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_transcription(audio_bytes: bytes, mime_type: str) -> str:
        raise routes.stt.STTProviderError("private provider response")

    monkeypatch.setattr(routes.stt, "transcribe", fail_transcription)
    monkeypatch.setattr(
        pipeline.extractor,
        "extract_transaction",
        lambda _: pytest.fail("pipeline must not run after STT failure"),
    )
    monkeypatch.setattr(
        routes.tts,
        "speak",
        lambda *args: pytest.fail("TTS must not run after STT failure"),
    )

    response = _voice_request(client)

    assert response.status_code == 502
    assert response.json()["transcript"] == ""
    assert response.json()["result"]["error"] == "stt_unavailable"
    assert "private provider response" not in response.text
    with closing(database.get_connection()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM pending_entries"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0] == 0


def test_empty_transcript_is_returned_as_unclear(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_voice_providers(monkeypatch, "")

    response = _voice_request(client)

    assert response.status_code == 200
    assert response.json()["transcript"] == ""
    assert response.json()["result"]["status"] == "unclear"


def test_voice_read_only_balance_skips_tts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    customer_id = ledger.add_customer("Asha")
    ledger.add_credit(customer_id, 200)
    _mock_extraction(
        monkeypatch,
        _extraction(intent="check_balance", amount=None, items=[]),
    )
    _mock_voice_providers(monkeypatch, "Asha balance")
    monkeypatch.setattr(
        routes.tts,
        "speak",
        lambda *args: pytest.fail("read-only balance response skips TTS"),
    )
    log_path = tmp_path / "voice_requests.jsonl"
    monkeypatch.setattr(routes, "VOICE_LOG_PATH", log_path)

    response = _voice_request(client)

    assert response.status_code == 200
    assert response.json()["transcript"] == "Asha balance"
    assert response.json()["result"]["balance"] == 200
    assert response.json()["audio"] is None
    assert response.json()["timings_ms"]["tts"] is None
    log_record = json.loads(log_path.read_text(encoding="utf-8"))
    assert log_record["extracted_json"] == _extraction(
        intent="check_balance",
        amount=None,
        items=[],
    ).model_dump(mode="json")


def test_tts_failure_does_not_hide_transcript_or_pending_card(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    monkeypatch.setattr(
        routes.stt,
        "transcribe",
        lambda audio_bytes, mime_type: "Asha bought rice",
    )
    monkeypatch.setattr(
        routes.tts,
        "speak",
        lambda *args: (_ for _ in ()).throw(routes.tts.TTSError("private error")),
    )

    response = _voice_request(client)

    assert response.status_code == 200
    assert response.json()["transcript"] == "Asha bought rice"
    assert response.json()["result"]["status"] == "confirmation_required"
    assert response.json()["result"]["audio_error"] == "tts_unavailable"
    assert ledger.get_customer_ledger(customer_id) == []


def test_invalid_voice_request_includes_transcript_field(
    client: TestClient,
) -> None:
    response = client.post("/api/voice")

    assert response.status_code == 400
    assert response.json()["transcript"] == ""
    assert response.json()["result"]["status"] == "invalid_audio"

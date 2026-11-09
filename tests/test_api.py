from contextlib import closing
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend import database, ledger, pipeline
from backend.main import app
from backend.models import TransactionExtraction


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "api_test.db")
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


def test_credit_is_saved_only_after_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())

    extracted = client.post("/api/text", json={"text": "Asha bought rice"})

    assert extracted.status_code == 200
    assert extracted.json()["status"] == "confirmation_required"
    assert ledger.get_customer_ledger(customer_id) == []

    confirmed = client.post(
        f"/api/confirm/{extracted.json()['pending_id']}"
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["balance"] == 250
    assert confirmed.json()["transaction"]["description"] == "rice"
    assert confirmed.json()["transaction"]["customer_id"] == customer_id
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_payment_confirmation_updates_balance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    ledger.add_credit(customer_id, 500)
    _mock_extraction(
        monkeypatch,
        _extraction(intent="add_payment", amount=150, description="cash"),
    )

    pending = client.post("/api/text", json={"text": "Asha paid 150"})
    assert pending.status_code == 200
    assert ledger.get_balance(customer_id) == 500

    confirmed = client.post(f"/api/confirm/{pending.json()['pending_id']}")

    assert confirmed.status_code == 200
    assert confirmed.json()["balance"] == 350
    assert confirmed.json()["transaction"]["transaction_type"] == "payment"


def test_balance_query_is_read_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    ledger.add_credit(customer_id, 400)
    _mock_extraction(
        monkeypatch,
        _extraction(intent="check_balance", amount=None, items=[]),
    )

    response = client.post("/api/text", json={"text": "What does Asha owe?"})

    assert response.status_code == 200
    assert response.json()["balance"] == 400
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_multiple_matches_remain_unresolved_until_customer_selected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id = ledger.add_customer("Suresh Kumar")
    second_id = ledger.add_customer("Suresh Reddy")
    extraction_calls = 0

    def extract(_: str) -> TransactionExtraction:
        nonlocal extraction_calls
        extraction_calls += 1
        return _extraction(customer_name="Suresh")

    monkeypatch.setattr(pipeline.extractor, "extract_transaction", extract)
    pending = client.post("/api/text", json={"text": "Suresh bought rice"})

    assert pending.status_code == 200
    assert pending.json()["status"] == "clarification_required"
    assert {match["customer_id"] for match in pending.json()["matches"]} == {
        first_id,
        second_id,
    }
    assert ledger.get_customer_ledger(first_id) == []
    assert ledger.get_customer_ledger(second_id) == []

    pending_id = pending.json()["pending_id"]
    selected = client.post(
        f"/api/pending/{pending_id}/customer",
        json={"customer_id": second_id},
    )
    assert selected.status_code == 200
    assert selected.json()["status"] == "confirmation_required"

    confirmed = client.post(f"/api/confirm/{pending_id}")
    assert confirmed.status_code == 200
    assert confirmed.json()["transaction"]["customer_id"] == second_id
    assert extraction_calls == 1


def test_customer_selection_rejects_id_outside_original_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")
    _mock_extraction(monkeypatch, _extraction(customer_name="Suresh"))
    pending = client.post("/api/text", json={"text": "Suresh bought rice"})
    pending_id = pending.json()["pending_id"]

    response = client.post(
        f"/api/pending/{pending_id}/customer",
        json={"customer_id": 999},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["status"] == "invalid_customer_selection"
    assert ledger.get_customer_ledger(1) == []
    assert ledger.get_customer_ledger(2) == []


def test_daily_summary_endpoint_is_read_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(
        monkeypatch,
        _extraction(
            intent="daily_summary",
            customer_name=None,
            amount=None,
            items=[],
        ),
    )

    response = client.get("/api/summary/today")
    text_response = client.post(
        "/api/text",
        json={"text": "How was today?"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_credits": 0,
        "total_payments": 0,
        "transaction_count": 0,
    }
    assert text_response.status_code == 200
    assert text_response.json()["status"] == "daily_summary"
    assert ledger.list_customers() == []


def test_read_only_api_requests_do_not_mutate_database(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    transaction_id = ledger.add_credit(customer_id, 200, "rice")

    def counts() -> tuple[int, int, int]:
        with closing(database.get_connection()) as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM customers),
                    (SELECT COUNT(*) FROM transactions),
                    (SELECT COUNT(*) FROM pending_entries)
                """
            ).fetchone()
        return (int(row[0]), int(row[1]), int(row[2]))

    before = counts()
    _mock_extraction(
        monkeypatch,
        _extraction(intent="check_balance", amount=None, items=[]),
    )
    assert client.post("/api/text", json={"text": "Asha balance"}).status_code == 200
    _mock_extraction(
        monkeypatch,
        _extraction(
            intent="daily_summary",
            customer_name=None,
            amount=None,
            items=[],
        ),
    )
    assert client.post("/api/text", json={"text": "Today's summary"}).status_code == 200
    assert client.get("/api/customers").status_code == 200
    assert client.get(f"/api/customers/{customer_id}/ledger").status_code == 200
    assert client.get("/api/summary/today").status_code == 200

    assert counts() == before
    assert ledger.get_customer_ledger(customer_id)[0]["id"] == transaction_id


def test_cancel_pending_prevents_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending = client.post("/api/text", json={"text": "Asha bought rice"})
    pending_id = pending.json()["pending_id"]

    cancelled = client.post(f"/api/cancel/{pending_id}")
    confirmation = client.post(f"/api/confirm/{pending_id}")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert confirmation.status_code == 409
    assert confirmation.json()["detail"]["status"] == "cancelled"
    assert ledger.get_customer_ledger(customer_id) == []


def test_repeated_confirmation_returns_conflict_without_duplicate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending = client.post("/api/text", json={"text": "Asha bought rice"})
    pending_id = pending.json()["pending_id"]

    first = client.post(f"/api/confirm/{pending_id}")
    second = client.post(f"/api/confirm/{pending_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["status"] == "already_confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_cancellation_after_confirmation_is_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending = client.post("/api/text", json={"text": "Asha bought rice"})
    pending_id = pending.json()["pending_id"]

    confirmation = client.post(f"/api/confirm/{pending_id}")
    cancellation = client.post(f"/api/cancel/{pending_id}")

    assert confirmation.status_code == 200
    assert cancellation.status_code == 409
    assert cancellation.json()["detail"]["status"] == "already_confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_undo_voids_without_deleting_ledger_history(
    client: TestClient,
) -> None:
    customer_id = ledger.add_customer("Asha")
    transaction_id = ledger.add_credit(customer_id, 300, "groceries")

    response = client.post("/api/undo", json={"customer_id": customer_id})

    assert response.status_code == 200
    assert response.json()["status"] == "voided"
    assert response.json()["transaction_id"] == transaction_id
    assert response.json()["balance"] == 0
    history = ledger.get_customer_ledger(customer_id)
    assert len(history) == 1
    assert history[0]["id"] == transaction_id
    assert history[0]["is_voided"] == 1


def test_undo_voids_latest_active_transaction_and_retains_all_history(
    client: TestClient,
) -> None:
    customer_id = ledger.add_customer("Asha")
    first_id = ledger.add_credit(customer_id, 100, "first")
    second_id = ledger.add_payment(customer_id, 30, "second")
    third_id = ledger.add_credit(customer_id, 50, "third")
    ledger.void_last(customer_id)

    response = client.post("/api/undo", json={"customer_id": customer_id})

    assert response.status_code == 200
    assert response.json()["transaction_id"] == second_id
    history = ledger.get_customer_ledger(customer_id)
    assert [entry["id"] for entry in history] == [
        first_id,
        second_id,
        third_id,
    ]
    assert [entry["is_voided"] for entry in history] == [0, 1, 1]


def test_customer_list_and_ledger_routes(
    client: TestClient,
) -> None:
    customer_id = ledger.add_customer("Asha")
    ledger.add_credit(customer_id, 125, "rice")

    customers = client.get("/api/customers")
    customer_ledger = client.get(f"/api/customers/{customer_id}/ledger")

    assert customers.status_code == 200
    assert [customer["name"] for customer in customers.json()["customers"]] == [
        "Asha"
    ]
    assert customer_ledger.status_code == 200
    assert customer_ledger.json()["balance"] == 125
    assert customer_ledger.json()["transactions"][0]["description"] == "rice"


def test_unknown_customer_is_not_created_from_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(
        monkeypatch,
        _extraction(customer_name="New Customer"),
    )

    response = client.post(
        "/api/text",
        json={"text": "New Customer bought rice"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "customer_not_found"
    assert ledger.list_customers() == []


def test_invalid_text_request_returns_validation_error(client: TestClient) -> None:
    assert client.post("/api/text", json={"text": "  "}).status_code == 422


def test_missing_api_resources_return_not_found(client: TestClient) -> None:
    assert client.post("/api/confirm/999").status_code == 404
    assert client.get("/api/customers/999/ledger").status_code == 404
    assert client.post("/api/undo", json={"customer_id": 999}).status_code == 404


def test_internal_database_errors_are_not_returned_to_clients(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_confirmation(_: int) -> dict[str, Any]:
        raise sqlite3.OperationalError(
            "private database path and internal query"
        )

    monkeypatch.setattr(pipeline, "confirm_pending", fail_confirmation)
    with TestClient(app, raise_server_exceptions=False) as quiet_client:
        response = quiet_client.post("/api/confirm/1")

    assert response.status_code == 500
    assert "private database path" not in response.text
    assert "internal query" not in response.text
    assert "Traceback" not in response.text

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from backend import database, ledger, pipeline, resolver
from backend.models import TransactionExtraction


pytestmark = pytest.mark.usefixtures("temporary_database")


@pytest.fixture
def temporary_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "kirana_test.db")
    database.init_db()


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
    monkeypatch: pytest.MonkeyPatch, extraction: object
) -> None:
    monkeypatch.setattr(
        pipeline.extractor, "extract_transaction", lambda _: extraction
    )


def _pending_count() -> int:
    with closing(database.get_connection()) as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM pending_entries").fetchone()[0]
        )


def _transaction_count() -> int:
    with closing(database.get_connection()) as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        )


def test_clear_customer_match_returns_confirmation_card_and_pending_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())

    result = pipeline.handle_text("Asha bought rice")

    assert result["status"] == "confirmation_required"
    assert result["pending_id"] == 1
    assert result["customer"]["customer_id"] == customer_id
    assert result["transaction"]["amount"] == 250
    assert result["expires_at"]
    assert ledger.get_customer_ledger(customer_id) == []
    with closing(database.get_connection()) as connection:
        row = connection.execute(
            """
            SELECT description, created_at, extraction_json
            FROM pending_entries
            WHERE id = ?
            """,
            (result["pending_id"],),
        ).fetchone()
    assert row is not None
    assert row[0] == "rice"
    assert json.loads(row[2]) == _extraction().model_dump(mode="json")
    expiration = datetime.fromisoformat(result["expires_at"])
    created_at = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )
    assert 299 <= (expiration - created_at).total_seconds() <= 301


def test_multiple_customer_matches_require_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")
    _mock_extraction(monkeypatch, _extraction(customer_name="Suresh"))

    result = pipeline.handle_text("Suresh borrowed rice")

    assert result["status"] == "clarification_required"
    assert result["question"] == "Which customer did you mean?"
    assert [match["customer_name"] for match in result["matches"]] == [
        "Suresh Kumar",
        "Suresh Reddy",
    ]
    assert result["pending_id"] == 1


def test_no_customer_match_asks_before_adding_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="New Customer"))

    result = pipeline.handle_text("New Customer bought rice")

    assert result["status"] == "customer_creation_confirmation"
    assert result["interaction_state"] == "customer_creation_confirmation"
    assert result["question"] == (
        "New Customer అనే కస్టమర్ లేరు. కొత్త కస్టమర్‌గా సృష్టించాలా?"
    )
    assert result["question_en"] == (
        "Customer New Customer does not exist. "
        "Would you like to create this customer?"
    )
    assert result["transaction"]["items"] == [
        {"name": "rice", "quantity": 2.0, "unit": "kg"}
    ]
    assert result["transaction"]["description"] == "rice"
    assert result["pending_id"] == 1
    assert resolver.resolve_customer("New Customer") == {
        "status": "not_found",
        "matches": [],
    }
    with closing(database.get_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


def test_customer_creation_confirmation_resumes_without_saving_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    initial = pipeline.handle_text("Ramu owes 500")
    original_pending_id = initial["pending_id"]

    resumed = pipeline.confirm_pending(original_pending_id)

    assert resumed["status"] == "confirmation_required"
    assert resumed["pending_id"] != original_pending_id
    assert resumed["customer_creation_pending_id"] == original_pending_id
    assert resumed["customer_created"] is True
    assert resumed["transaction"] == initial["transaction"]
    assert len(ledger.list_customers()) == 1
    customer_id = resumed["customer"]["customer_id"]
    assert ledger.get_customer_ledger(customer_id) == []
    assert pipeline.get_pending_entry(original_pending_id)["interaction_state"] == (
        "customer_created"
    )

    repeated_creation_confirmation = pipeline.confirm_pending(original_pending_id)
    assert repeated_creation_confirmation["status"] == "confirmation_required"
    assert repeated_creation_confirmation["pending_id"] == resumed["pending_id"]
    assert ledger.get_customer_ledger(customer_id) == []

    confirmed = pipeline.confirm_pending(resumed["pending_id"])
    repeated_transaction_confirmation = pipeline.confirm_pending(resumed["pending_id"])
    assert confirmed["status"] == "confirmed"
    assert repeated_transaction_confirmation["status"] == "already_confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1
    assert _transaction_count() == 1


def test_concurrent_confirmation_of_same_customer_creation_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")
    barrier = Barrier(2)

    def confirm_at_once() -> dict[str, Any]:
        barrier.wait()
        return pipeline.confirm_pending(pending["pending_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm_at_once(), range(2)))

    assert [result["status"] for result in results] == [
        "confirmation_required",
        "confirmation_required",
    ]
    resumed_pending_ids = {result["pending_id"] for result in results}
    assert len(resumed_pending_ids) == 1
    with closing(database.get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT id, interaction_state, resumed_pending_id
            FROM pending_entries
            ORDER BY id
            """
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == pending["pending_id"]
    assert rows[0][1] == "customer_created"
    assert rows[0][2] in resumed_pending_ids
    assert rows[1][0] in resumed_pending_ids
    assert len(ledger.list_customers()) == 1
    assert _transaction_count() == 0
    assert ledger.get_customer_ledger(results[0]["customer"]["customer_id"]) == []


def test_declining_customer_creation_cancels_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")

    cancelled = pipeline.cancel_pending(pending["pending_id"])

    assert cancelled["status"] == "cancelled"
    assert ledger.list_customers() == []
    assert _transaction_count() == 0
    assert pipeline.confirm_pending(pending["pending_id"])["status"] == "cancelled"


def test_cancellation_racing_customer_creation_leaves_consistent_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")
    barrier = Barrier(2)

    def confirm_at_once() -> dict[str, Any]:
        barrier.wait()
        return pipeline.confirm_pending(pending["pending_id"])

    def cancel_at_once() -> dict[str, Any]:
        barrier.wait()
        return pipeline.cancel_pending(pending["pending_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        confirmation_future = executor.submit(confirm_at_once)
        cancellation_future = executor.submit(cancel_at_once)
        confirmation = confirmation_future.result()
        cancellation = cancellation_future.result()

    assert cancellation["status"] == "cancelled"
    assert confirmation["status"] in {
        "cancelled",
        "confirmation_required",
    }
    with closing(database.get_connection()) as connection:
        pending_rows = connection.execute(
            """
            SELECT id, interaction_state, resumed_pending_id, cancelled_at
            FROM pending_entries
            ORDER BY id
            """
        ).fetchall()
        customer_ids = [
            row[0] for row in connection.execute("SELECT id FROM customers")
        ]

    assert _transaction_count() == 0
    assert len(customer_ids) in {0, 1}
    assert pending_rows[0][0] == pending["pending_id"]
    assert pending_rows[0][3] is not None
    if not customer_ids:
        assert len(pending_rows) == 1
        assert pending_rows[0][1] == "customer_creation_confirmation"
        assert pending_rows[0][2] is None
    else:
        assert len(pending_rows) == 2
        assert pending_rows[0][1] == "customer_created"
        assert pending_rows[0][2] == pending_rows[1][0]
        assert pending_rows[1][3] is not None
        assert pending_rows[1][1] == "transaction_confirmation"
        assert ledger.get_customer_ledger(customer_ids[0]) == []


def test_customer_created_concurrently_is_reused_before_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")
    existing_id = ledger.add_customer("Ramu")

    resumed = pipeline.confirm_pending(pending["pending_id"])

    assert resumed["status"] == "confirmation_required"
    assert resumed["customer_created"] is False
    assert resumed["customer"]["customer_id"] == existing_id
    assert len(ledger.list_customers()) == 1
    assert ledger.get_customer_ledger(existing_id) == []
    assert _transaction_count() == 0


def test_expired_customer_creation_request_is_not_resumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")
    with closing(database.get_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE pending_entries
            SET created_at = datetime('now', '-6 minutes')
            WHERE id = ?
            """,
            (pending["pending_id"],),
        )

    result = pipeline.confirm_pending(pending["pending_id"])

    assert result["status"] == "expired"
    assert ledger.list_customers() == []
    assert _transaction_count() == 0


def test_concurrent_customer_creation_requests_do_not_duplicate_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    first = pipeline.handle_text("Ramu owes 500")
    second = pipeline.handle_text("Ramu owes 500")
    barrier = Barrier(2)

    def confirm_at_once(pending_id: int) -> dict[str, Any]:
        barrier.wait()
        return pipeline.confirm_pending(pending_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                confirm_at_once,
                (first["pending_id"], second["pending_id"]),
            )
        )

    assert [result["status"] for result in results] == [
        "confirmation_required",
        "confirmation_required",
    ]
    assert len(ledger.list_customers()) == 1
    assert _transaction_count() == 0


def test_customer_creation_and_resumed_pending_failure_rolls_back_completely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending = pipeline.handle_text("Ramu owes 500")
    insert_pending_entry = pipeline._insert_pending_entry

    def insert_then_fail(*args: Any, **kwargs: Any) -> int:
        insert_pending_entry(*args, **kwargs)
        raise sqlite3.IntegrityError("injected resumed-pending failure")

    monkeypatch.setattr(pipeline, "_insert_pending_entry", insert_then_fail)

    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        pipeline.confirm_pending(pending["pending_id"])

    assert ledger.list_customers() == []
    assert _pending_count() == 1
    assert _transaction_count() == 0
    with closing(database.get_connection()) as connection:
        row = connection.execute(
            """
            SELECT customer_id, interaction_state, resumed_pending_id,
                   cancelled_at, status
            FROM pending_entries
            WHERE id = ?
            """,
            (pending["pending_id"],),
        ).fetchone()
    assert row == (
        None,
        "customer_creation_confirmation",
        None,
        None,
        "pending",
    )


def test_existing_resolution_rules_are_used_before_creating_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Suresh"))
    pending = pipeline.handle_text("Suresh owes 500")
    ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")

    result = pipeline.confirm_pending(pending["pending_id"])

    assert result["status"] == "clarification_required"
    assert [match["customer_name"] for match in result["matches"]] == [
        "Suresh Kumar",
        "Suresh Reddy",
    ]
    assert len(ledger.list_customers()) == 2
    assert _transaction_count() == 0


def test_balance_query_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    ledger.add_credit(customer_id, 300)
    _mock_extraction(
        monkeypatch,
        _extraction(intent="check_balance", amount=None, items=[]),
    )

    result = pipeline.handle_text("What does Asha owe?")

    assert result["status"] == "balance"
    assert result["balance"] == 300
    assert result["customer"]["customer_id"] == customer_id
    assert _pending_count() == 0


def test_daily_summary_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(
        monkeypatch,
        _extraction(intent="daily_summary", customer_name=None, amount=None, items=[]),
    )

    result = pipeline.handle_text("How was today?")

    assert result == {
        "status": "daily_summary",
        "intent": "daily_summary",
        "summary": {
            "total_credits": 0,
            "total_payments": 0,
            "transaction_count": 0,
        },
    }
    assert _pending_count() == 0


def test_unknown_intent_does_not_create_pending_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(
        monkeypatch,
        _extraction(
            intent="unknown",
            customer_name=None,
            amount=None,
            amount_ambiguous=True,
            items=[],
        ),
    )

    result = pipeline.handle_text("Say something unclear")

    assert result["status"] == "unknown_intent"
    assert result["intent"] == "unknown"
    assert _pending_count() == 0


def test_invalid_extraction_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, {"intent": "credit", "amount": -1})

    result = pipeline.handle_text("Invalid extraction")

    assert result["status"] == "invalid_extraction"
    assert result["intent"] == "unknown"
    assert _pending_count() == 0


def test_expired_pending_entry_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending_id = pipeline.handle_text("Asha bought rice")["pending_id"]
    with closing(database.get_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE pending_entries
            SET created_at = datetime('now', '-6 minutes')
            WHERE id = ?
            """,
            (pending_id,),
        )

    retrieved = pipeline.get_pending_entry(pending_id)
    confirmation = pipeline.confirm_pending(pending_id)

    assert retrieved["status"] == "expired"
    assert confirmation["status"] == "expired"
    assert ledger.get_customer_ledger(customer_id) == []
    assert _transaction_count() == 0


def test_pending_expiration_boundary_is_inclusive_at_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(monkeypatch, _extraction(customer_name="Ramu"))
    pending_ids = [
        pipeline.handle_text("Ramu owes 500")["pending_id"]
        for _ in range(3)
    ]
    fixed_now = datetime.now(timezone.utc).replace(microsecond=0)
    created_at_values = (
        fixed_now - timedelta(minutes=5) + timedelta(seconds=1),
        fixed_now - timedelta(minutes=5),
        fixed_now - timedelta(minutes=5, seconds=1),
    )
    with closing(database.get_connection()) as connection, connection:
        connection.executemany(
            "UPDATE pending_entries SET created_at = ? WHERE id = ?",
            [
                (created_at.strftime("%Y-%m-%d %H:%M:%S"), pending_id)
                for pending_id, created_at in zip(
                    pending_ids,
                    created_at_values,
                    strict=True,
                )
            ],
        )

    get_connection = pipeline.get_connection

    def connection_with_fixed_clock() -> sqlite3.Connection:
        connection = get_connection()

        def fixed_datetime(value: str, *modifiers: str) -> str:
            current = (
                fixed_now
                if value == "now"
                else datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            )
            for modifier in modifiers:
                amount, unit = modifier.split()
                delta = timedelta(**{unit: int(amount)})
                current += delta
            return current.strftime("%Y-%m-%d %H:%M:%S")

        connection.create_function("datetime", -1, fixed_datetime)
        return connection

    monkeypatch.setattr(pipeline, "get_connection", connection_with_fixed_clock)

    before_expiry = pipeline.get_pending_entry(pending_ids[0])
    exactly_at_expiry = pipeline.get_pending_entry(pending_ids[1])
    after_expiry = pipeline.get_pending_entry(pending_ids[2])

    assert before_expiry["status"] == "pending"
    assert exactly_at_expiry["status"] == "expired"
    assert after_expiry["status"] == "expired"


def test_pending_entry_cannot_be_confirmed_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending_id = pipeline.handle_text("Asha bought rice")["pending_id"]

    first = pipeline.confirm_pending(pending_id)
    second = pipeline.confirm_pending(pending_id)

    assert first["status"] == "confirmed"
    assert second["status"] == "already_confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_failed_ledger_insert_rolls_back_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending_id = pipeline.handle_text("Asha bought rice")["pending_id"]
    insert_on_connection = ledger._add_transaction_on_connection

    def fail_insert(
        connection: sqlite3.Connection,
        customer_id: int,
        amount: int,
        transaction_type: str,
        description: str | None,
    ) -> int:
        assert connection.in_transaction
        assert customer_id > 0
        assert (amount, transaction_type, description) == (
            250,
            "credit",
            "rice",
        )
        raise sqlite3.IntegrityError("injected ledger insert failure")

    monkeypatch.setattr(ledger, "_add_transaction_on_connection", fail_insert)
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        pipeline.confirm_pending(pending_id)

    with closing(database.get_connection()) as connection:
        state = connection.execute(
            "SELECT status FROM pending_entries WHERE id = ?", (pending_id,)
        ).fetchone()
    assert state == ("pending",)
    assert _transaction_count() == 0

    monkeypatch.setattr(
        ledger, "_add_transaction_on_connection", insert_on_connection
    )
    result = pipeline.confirm_pending(pending_id)

    assert result["status"] == "confirmed"
    assert len(ledger.get_customer_ledger(customer_id)) == 1


def test_database_lock_returns_retryable_result_without_claiming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending_id = pipeline.handle_text("Asha bought rice")["pending_id"]
    insert_on_connection = ledger._add_transaction_on_connection

    def fail_with_lock(
        connection: sqlite3.Connection,
        customer_id: int,
        amount: int,
        transaction_type: str,
        description: str | None,
    ) -> int:
        assert connection.in_transaction
        assert customer_id > 0
        assert (amount, transaction_type, description) == (
            250,
            "credit",
            "rice",
        )
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, "_add_transaction_on_connection", fail_with_lock)

    result = pipeline.confirm_pending(pending_id)

    assert result == {
        "status": "retryable_error",
        "pending_id": pending_id,
        "retryable": True,
    }
    with closing(database.get_connection()) as connection:
        state = connection.execute(
            "SELECT status FROM pending_entries WHERE id = ?", (pending_id,)
        ).fetchone()
    assert state == ("pending",)
    assert _transaction_count() == 0

    monkeypatch.setattr(
        ledger, "_add_transaction_on_connection", insert_on_connection
    )
    assert pipeline.confirm_pending(pending_id)["status"] == "confirmed"


def test_concurrent_confirmation_creates_at_most_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction())
    pending_id = pipeline.handle_text("Asha bought rice")["pending_id"]
    barrier = Barrier(2)

    def confirm_at_once() -> dict[str, Any]:
        barrier.wait()
        return pipeline.confirm_pending(pending_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm_at_once(), range(2)))

    statuses = [result["status"] for result in results]
    assert statuses.count("confirmed") == 1
    assert set(statuses) <= {
        "confirmed",
        "already_confirmed",
        "confirmation_in_progress",
    }
    assert len(ledger.get_customer_ledger(customer_id)) == 1
    assert _transaction_count() == 1


def test_confirmation_uses_original_extraction_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id = ledger.add_customer("Asha")
    _mock_extraction(monkeypatch, _extraction(description="rice and lentils"))
    pending_id = pipeline.handle_text("Asha bought rice and lentils")["pending_id"]

    result = pipeline.confirm_pending(pending_id)

    assert result["status"] == "confirmed"
    entries = ledger.get_customer_ledger(customer_id)
    assert entries[0]["description"] == "rice and lentils"
    pending = pipeline.get_pending_entry(pending_id)
    assert pending["status"] == "already_confirmed"


def test_multiple_customer_selection_continues_without_reextraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_customer_id = ledger.add_customer("Suresh Kumar")
    second_customer_id = ledger.add_customer("Suresh Reddy")
    extraction_calls = 0

    def extract(_: str) -> TransactionExtraction:
        nonlocal extraction_calls
        extraction_calls += 1
        return _extraction(customer_name="Suresh")

    monkeypatch.setattr(pipeline.extractor, "extract_transaction", extract)
    initial = pipeline.handle_text("Suresh borrowed rice")

    continuation = pipeline.select_pending_customer(
        initial["pending_id"], second_customer_id
    )
    confirmed = pipeline.confirm_pending(initial["pending_id"])

    assert initial["status"] == "clarification_required"
    assert {match["customer_id"] for match in initial["matches"]} == {
        first_customer_id,
        second_customer_id,
    }
    assert continuation["status"] == "confirmation_required"
    assert continuation["customer"]["customer_id"] == second_customer_id
    assert confirmed["status"] == "confirmed"
    assert ledger.get_customer_ledger(second_customer_id)[0]["description"] == "rice"
    assert extraction_calls == 1


def test_multiple_customer_selection_rejects_non_candidate_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_customer_id = ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")
    _mock_extraction(monkeypatch, _extraction(customer_name="Suresh"))
    pending = pipeline.handle_text("Suresh bought rice")

    result = pipeline.select_pending_customer(pending["pending_id"], 999)

    assert result["status"] == "invalid_customer_selection"
    assert ledger.get_customer_ledger(first_customer_id) == []
    assert _transaction_count() == 0


def test_unknown_balance_customer_is_not_an_add_customer_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_extraction(
        monkeypatch,
        _extraction(intent="check_balance", customer_name="Unknown Person", amount=None),
    )

    result = pipeline.handle_text("What does Unknown Person owe?")

    assert result["status"] == "customer_not_found"
    assert "Would you like to add" not in result["question"]
    assert _pending_count() == 0
    with closing(database.get_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


def test_init_db_migrates_legacy_pending_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)
    legacy_extraction = _extraction().model_dump(mode="json")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE pending_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                transaction_type TEXT,
                amount INTEGER,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO pending_entries
                (customer_id, transaction_type, amount, description, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (
                7,
                "credit",
                250,
                json.dumps(
                    {
                        "description": "rice",
                        "extraction": legacy_extraction,
                    }
                ),
            ),
        )

    database.init_db()

    entry = pipeline.get_pending_entry(1)
    assert entry["status"] == "pending"
    assert entry["description"] == "rice"
    assert entry["extraction"] == legacy_extraction
    assert entry["candidate_customer_ids"] == [7]
    with closing(database.get_connection()) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(pending_entries)")
        }
    assert {
        "status",
        "extraction_json",
        "candidate_customer_ids_json",
        "cancelled_at",
        "interaction_state",
        "resumed_pending_id",
    } <= columns

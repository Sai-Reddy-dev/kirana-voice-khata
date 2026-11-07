from pathlib import Path

import pytest

from backend import database, ledger


@pytest.fixture
def temporary_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "kirana_test.db")
    database.init_db()


@pytest.fixture
def customer_id(temporary_database: None) -> int:
    return ledger.add_customer("Asha")


def test_add_customer_and_reject_duplicate(temporary_database: None) -> None:
    customer_id = ledger.add_customer("  Asha   Devi ")

    assert customer_id > 0
    with pytest.raises(ValueError, match="already exists"):
        ledger.add_customer("asha devi")


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_reject_blank_customer_name(
    temporary_database: None, name: str
) -> None:
    with pytest.raises(ValueError):
        ledger.add_customer(name)


def test_credit_and_payment_balance(customer_id: int) -> None:
    ledger.add_credit(customer_id, 250)
    ledger.add_payment(customer_id, 100)

    assert ledger.get_balance(customer_id) == 150


def test_void_last_payment_restores_balance_and_retains_ledger_entry(
    customer_id: int,
) -> None:
    ledger.add_credit(customer_id, 250)
    payment_id = ledger.add_payment(customer_id, 100)

    assert ledger.void_last(customer_id) == payment_id
    assert ledger.get_balance(customer_id) == 250
    entries = ledger.get_customer_ledger(customer_id)
    assert len(entries) == 2
    assert entries[1]["id"] == payment_id
    assert entries[1]["transaction_type"] == "payment"
    assert entries[1]["is_voided"] == 1


@pytest.mark.parametrize(
    "add_transaction",
    [ledger.add_credit, ledger.add_payment],
    ids=["credit", "payment"],
)
@pytest.mark.parametrize("amount", [0, -1])
def test_reject_non_positive_transaction_amount(
    customer_id: int, add_transaction, amount: int
) -> None:
    with pytest.raises(ValueError):
        add_transaction(customer_id, amount)


def test_reject_unknown_customer_id(temporary_database: None) -> None:
    with pytest.raises(ValueError, match="Unknown customer ID"):
        ledger.add_credit(999, 100)
    with pytest.raises(ValueError, match="Unknown customer ID"):
        ledger.add_payment(999, 100)
    with pytest.raises(ValueError, match="Unknown customer ID"):
        ledger.get_balance(999)
    with pytest.raises(ValueError, match="Unknown customer ID"):
        ledger.get_customer_ledger(999)
    with pytest.raises(ValueError, match="Unknown customer ID"):
        ledger.void_last(999)


def test_void_last_rejects_customer_without_transactions(customer_id: int) -> None:
    with pytest.raises(ValueError, match="No non-voided transactions"):
        ledger.void_last(customer_id)


def test_daily_summary_excludes_voided_transactions(customer_id: int) -> None:
    ledger.add_credit(customer_id, 250)
    ledger.add_payment(customer_id, 100)
    ledger.void_last(customer_id)

    assert ledger.daily_summary() == {
        "total_credits": 250,
        "total_payments": 0,
        "transaction_count": 1,
    }

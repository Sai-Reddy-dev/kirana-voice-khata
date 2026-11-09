import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from . import extractor, ledger
from .database import get_connection
from .models import CustomerResolution, TransactionExtraction
from .resolver import resolve_customer


_PENDING_ENTRY_TTL = timedelta(minutes=5)


def _serialize_extraction(extraction: TransactionExtraction) -> dict[str, Any]:
    return extraction.model_dump(mode="json")


def _validate_pending_id(pending_id: int) -> None:
    if type(pending_id) is not int or pending_id <= 0:
        raise ValueError("pending_id must be a positive integer")


def _expiration(created_at: str) -> datetime:
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created + _PENDING_ENTRY_TTL


def _unavailable_result(
    pending_id: int,
    status: str,
    created_at: str,
) -> dict[str, Any]:
    mapped_status = {
        "confirmed": "already_confirmed",
        "processing": "confirmation_in_progress",
    }.get(status, status)
    return {
        "status": mapped_status,
        "pending_id": pending_id,
        "expires_at": _expiration(created_at).isoformat(),
    }


def _pending_row(
    connection: sqlite3.Connection,
    pending_id: int,
) -> tuple[Any, ...] | None:
    connection.execute(
        """
        UPDATE pending_entries
        SET status = 'expired'
        WHERE id = ?
          AND status = 'pending'
          AND cancelled_at IS NULL
          AND datetime(created_at) <= datetime('now', '-5 minutes')
        """,
        (pending_id,),
    )
    return connection.execute(
        """
        SELECT id, customer_id, transaction_type, amount, description,
               created_at, status, extraction_json,
               candidate_customer_ids_json, cancelled_at
        FROM pending_entries
        WHERE id = ?
        """,
        (pending_id,),
    ).fetchone()


def _entry_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    if row[7] is None:
        raise ValueError(f"Pending entry {row[0]} has no recoverable extraction")
    extraction = TransactionExtraction.model_validate_json(row[7])
    candidate_customer_ids = json.loads(row[8])
    return {
        "status": "pending",
        "pending_id": int(row[0]),
        "customer_id": row[1],
        "transaction_type": row[2],
        "amount": row[3],
        "description": row[4],
        "extraction": _serialize_extraction(extraction),
        "candidate_customer_ids": candidate_customer_ids,
        "expires_at": _expiration(row[5]).isoformat(),
    }


def _create_pending_entry(
    extraction: TransactionExtraction,
    customer_id: int | None,
    candidate_customer_ids: list[int] | None = None,
) -> tuple[int, str]:
    transaction_type = {
        "add_credit": "credit",
        "add_payment": "payment",
    }.get(extraction.intent)
    if transaction_type is None:
        raise ValueError("pending entries require a transaction intent")

    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = created_at + _PENDING_ENTRY_TTL
    candidates = candidate_customer_ids or (
        [customer_id] if customer_id is not None else []
    )

    with closing(get_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE pending_entries
            SET status = 'expired'
            WHERE status = 'pending'
              AND cancelled_at IS NULL
              AND datetime(created_at) <= datetime('now', '-5 minutes')
            """
        )
        cursor = connection.execute(
            """
            INSERT INTO pending_entries (
                customer_id, transaction_type, amount, description,
                created_at, extraction_json, candidate_customer_ids_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                transaction_type,
                None if extraction.amount_ambiguous else extraction.amount,
                extraction.description,
                created_at.strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(_serialize_extraction(extraction), ensure_ascii=False),
                json.dumps(candidates),
            ),
        )

    return int(cursor.lastrowid), expires_at.isoformat()


def _transaction_details(
    extraction: TransactionExtraction,
) -> dict[str, Any]:
    return {
        "transaction_type": (
            "credit" if extraction.intent == "add_credit" else "payment"
        ),
        "amount": extraction.amount,
        "description": extraction.description,
        "items": [item.model_dump(mode="json") for item in extraction.items],
        "confidence": extraction.confidence,
        "amount_ambiguous": extraction.amount_ambiguous,
        "customer_name": extraction.customer_name,
    }


def _resolve(customer_name: str) -> CustomerResolution:
    return CustomerResolution.model_validate(resolve_customer(customer_name))


def _customer_not_found(
    extraction: TransactionExtraction,
    pending_id: int | None = None,
    expires_at: str | None = None,
    *,
    invite_to_add: bool = True,
) -> dict[str, Any]:
    question = f"I couldn't find {extraction.customer_name}."
    if invite_to_add:
        question += " Would you like to add this customer?"
    result: dict[str, Any] = {
        "status": "customer_not_found",
        "intent": extraction.intent,
        "customer_name": extraction.customer_name,
        "question": question,
    }
    if pending_id is not None:
        result["pending_id"] = pending_id
        result["expires_at"] = expires_at
        result["transaction"] = _transaction_details(extraction)
    return result


def get_pending_entry(pending_id: int) -> dict[str, Any]:
    _validate_pending_id(pending_id)
    with closing(get_connection()) as connection, connection:
        row = _pending_row(connection, pending_id)
        if row is None:
            return {"status": "not_found", "pending_id": pending_id}
        if row[9] is not None:
            return _unavailable_result(pending_id, "cancelled", row[5])
        if row[6] != "pending":
            return _unavailable_result(pending_id, row[6], row[5])
        return _entry_from_row(row)


def select_pending_customer(
    pending_id: int,
    customer_id: int,
) -> dict[str, Any]:
    _validate_pending_id(pending_id)
    if type(customer_id) is not int or customer_id <= 0:
        raise ValueError("customer_id must be a positive integer")

    with closing(get_connection()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _pending_row(connection, pending_id)
        if row is None:
            return {"status": "not_found", "pending_id": pending_id}
        if row[9] is not None:
            return _unavailable_result(pending_id, "cancelled", row[5])
        if row[6] != "pending":
            return _unavailable_result(pending_id, row[6], row[5])
        entry = _entry_from_row(row)
        if customer_id not in entry["candidate_customer_ids"]:
            return {
                "status": "invalid_customer_selection",
                "pending_id": pending_id,
                "question": "Please select one of the listed customers.",
            }

        cursor = connection.execute(
            """
            UPDATE pending_entries
            SET customer_id = ?
            WHERE id = ?
              AND status = 'pending'
              AND datetime(created_at) > datetime('now', '-5 minutes')
            """,
            (customer_id, pending_id),
        )
        if cursor.rowcount != 1:
            return _unavailable_result(pending_id, "expired", row[5])

        customer_row = connection.execute(
            "SELECT id, name FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()

    if customer_row is None:
        raise ValueError(f"Unknown customer ID: {customer_id}")

    entry["customer_id"] = customer_id
    extraction = TransactionExtraction.model_validate(entry["extraction"])
    return {
        "status": "confirmation_required",
        "intent": extraction.intent,
        "pending_id": pending_id,
        "expires_at": entry["expires_at"],
        "customer": {
            "customer_id": int(customer_row[0]),
            "customer_name": customer_row[1],
        },
        "transaction": _transaction_details(extraction),
    }


def confirm_pending(pending_id: int) -> dict[str, Any]:
    _validate_pending_id(pending_id)
    connection: sqlite3.Connection | None = None

    try:
        with closing(get_connection()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE pending_entries
                    SET status = 'expired'
                    WHERE id = ?
                      AND status = 'pending'
                      AND cancelled_at IS NULL
                      AND datetime(created_at) <= datetime('now', '-5 minutes')
                    """,
                    (pending_id,),
                )
                row = connection.execute(
                    """
                    SELECT id, customer_id, transaction_type, amount, description,
                           created_at, status, extraction_json, cancelled_at
                    FROM pending_entries
                    WHERE id = ?
                    """,
                    (pending_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return {"status": "not_found", "pending_id": pending_id}
                if row[6] == "expired":
                    connection.commit()
                    return _unavailable_result(pending_id, row[6], row[5])
                if row[8] is not None:
                    connection.rollback()
                    return _unavailable_result(pending_id, "cancelled", row[5])
                if row[6] != "pending":
                    connection.rollback()
                    return _unavailable_result(pending_id, row[6], row[5])
                if row[1] is None:
                    connection.rollback()
                    return {
                        "status": "customer_required",
                        "pending_id": pending_id,
                        "expires_at": _expiration(row[5]).isoformat(),
                    }
                if row[3] is None:
                    connection.rollback()
                    return {
                        "status": "amount_required",
                        "pending_id": pending_id,
                        "expires_at": _expiration(row[5]).isoformat(),
                    }

                extraction = TransactionExtraction.model_validate_json(row[7])
                if extraction.amount_ambiguous:
                    connection.rollback()
                    return {
                        "status": "amount_required",
                        "pending_id": pending_id,
                        "expires_at": _expiration(row[5]).isoformat(),
                    }

                transaction_type = {
                    "credit": "credit",
                    "payment": "payment",
                }.get(row[2])
                if transaction_type is None:
                    raise ValueError(
                        f"Unsupported pending transaction type: {row[2]}"
                    )

                transaction_id = ledger._add_transaction_on_connection(
                    connection,
                    row[1],
                    row[3],
                    transaction_type,
                    row[4],
                )
                transaction_row = connection.execute(
                    """
                    SELECT id, customer_id, transaction_type, amount, description,
                           created_at, is_voided
                    FROM transactions
                    WHERE id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
                if transaction_row is None:
                    raise RuntimeError(
                        f"Inserted transaction {transaction_id} could not be read"
                    )
                transaction = dict(
                    zip(
                        (
                            "id",
                            "customer_id",
                            "transaction_type",
                            "amount",
                            "description",
                            "created_at",
                            "is_voided",
                        ),
                        transaction_row,
                    )
                )
                balance = ledger._get_balance_on_connection(connection, row[1])
                cursor = connection.execute(
                    """
                    UPDATE pending_entries
                    SET status = 'confirmed'
                    WHERE id = ? AND status = 'pending'
                    """,
                    (pending_id,),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Pending entry {pending_id} lost its confirmation state"
                    )
                connection.commit()
            except sqlite3.OperationalError as error:
                if connection.in_transaction:
                    connection.rollback()
                message = str(error).lower()
                if "locked" in message or "busy" in message:
                    return {
                        "status": "retryable_error",
                        "pending_id": pending_id,
                        "retryable": True,
                    }
                raise
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            return {
                "status": "retryable_error",
                "pending_id": pending_id,
                "retryable": True,
            }
        raise

    return {
        "status": "confirmed",
        "pending_id": pending_id,
        "transaction_id": transaction_id,
        "transaction": transaction,
        "balance": balance,
    }


def cancel_pending(pending_id: int) -> dict[str, Any]:
    _validate_pending_id(pending_id)

    try:
        with closing(get_connection()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = _pending_row(connection, pending_id)
                if row is None:
                    connection.rollback()
                    return {"status": "not_found", "pending_id": pending_id}
                if row[9] is not None:
                    connection.rollback()
                    return _unavailable_result(pending_id, "cancelled", row[5])
                if row[6] == "expired":
                    connection.commit()
                    return _unavailable_result(pending_id, row[6], row[5])
                if row[6] != "pending":
                    connection.rollback()
                    return _unavailable_result(pending_id, row[6], row[5])

                cursor = connection.execute(
                    """
                    UPDATE pending_entries
                    SET cancelled_at = datetime('now')
                    WHERE id = ? AND status = 'pending' AND cancelled_at IS NULL
                    """,
                    (pending_id,),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return get_pending_entry(pending_id)
                connection.commit()
            except sqlite3.OperationalError as error:
                if connection.in_transaction:
                    connection.rollback()
                message = str(error).lower()
                if "locked" in message or "busy" in message:
                    return {
                        "status": "retryable_error",
                        "pending_id": pending_id,
                        "retryable": True,
                    }
                raise
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            return {
                "status": "retryable_error",
                "pending_id": pending_id,
                "retryable": True,
            }
        raise

    return {
        "status": "cancelled",
        "pending_id": pending_id,
        "expires_at": _expiration(row[5]).isoformat(),
    }


def handle_text(text: str) -> dict[str, Any]:
    if not text.strip():
        return {
            "status": "invalid_input",
            "question": "Please say or enter a transaction or question.",
        }

    extracted = extractor.extract_transaction(text)
    try:
        extraction = TransactionExtraction.model_validate(extracted)
    except ValidationError:
        return {
            "status": "invalid_extraction",
            "intent": "unknown",
            "question": "I couldn't understand that. Please try again.",
        }

    if extraction.intent == "daily_summary":
        return {
            "status": "daily_summary",
            "intent": extraction.intent,
            "summary": ledger.daily_summary(),
        }

    if extraction.intent == "check_balance":
        if not extraction.customer_name or not extraction.customer_name.strip():
            return {
                "status": "clarification_required",
                "intent": extraction.intent,
                "question": "Whose balance would you like to check?",
            }

        resolution = _resolve(extraction.customer_name)
        if resolution.status == "multiple_matches":
            return {
                "status": "clarification_required",
                "intent": extraction.intent,
                "question": "Which customer did you mean?",
                "matches": [
                    match.model_dump(mode="json") for match in resolution.matches
                ],
            }
        if resolution.status == "not_found":
            return _customer_not_found(extraction, invite_to_add=False)

        customer = resolution.matches[0]
        return {
            "status": "balance",
            "intent": extraction.intent,
            "customer": customer.model_dump(mode="json"),
            "balance": ledger.get_balance(customer.customer_id),
        }

    if extraction.intent not in {"add_credit", "add_payment"}:
        return {
            "status": "unknown_intent",
            "intent": extraction.intent,
            "question": (
                "I can record a credit or payment, check a balance, "
                "or provide today's summary. What would you like to do?"
            ),
        }

    customer_resolution = (
        _resolve(extraction.customer_name)
        if extraction.customer_name and extraction.customer_name.strip()
        else None
    )
    customer_id = (
        customer_resolution.matches[0].customer_id
        if customer_resolution is not None
        and customer_resolution.status == "matched"
        else None
    )
    candidate_customer_ids = (
        [match.customer_id for match in customer_resolution.matches]
        if customer_resolution is not None
        and customer_resolution.status == "multiple_matches"
        else ([customer_id] if customer_id is not None else [])
    )
    pending_id, expires_at = _create_pending_entry(
        extraction,
        customer_id,
        candidate_customer_ids,
    )
    details = _transaction_details(extraction)

    if extraction.amount_ambiguous or extraction.amount is None:
        return {
            "status": "clarification_required",
            "intent": extraction.intent,
            "pending_id": pending_id,
            "expires_at": expires_at,
            "question": "What amount should I record?",
            "transaction": details,
        }

    if customer_resolution is None:
        return {
            "status": "clarification_required",
            "intent": extraction.intent,
            "pending_id": pending_id,
            "expires_at": expires_at,
            "question": "Which customer is this transaction for?",
            "transaction": details,
        }

    if customer_resolution.status == "multiple_matches":
        return {
            "status": "clarification_required",
            "intent": extraction.intent,
            "pending_id": pending_id,
            "expires_at": expires_at,
            "question": "Which customer did you mean?",
            "matches": [
                match.model_dump(mode="json")
                for match in customer_resolution.matches
            ],
            "transaction": details,
        }

    if customer_resolution.status == "not_found":
        return _customer_not_found(extraction, pending_id, expires_at)

    return {
        "status": "confirmation_required",
        "intent": extraction.intent,
        "pending_id": pending_id,
        "expires_at": expires_at,
        "customer": customer_resolution.matches[0].model_dump(mode="json"),
        "transaction": details,
    }

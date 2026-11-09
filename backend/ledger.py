import sqlite3
from contextlib import closing

from .database import get_connection
from .models import CustomerCreate, TransactionCreate


def _validate_positive_integer(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_customer(connection: sqlite3.Connection, customer_id: int) -> None:
    if connection.execute(
        "SELECT 1 FROM customers WHERE id = ?", (customer_id,)
    ).fetchone() is None:
        raise ValueError(f"Unknown customer ID: {customer_id}")


def _add_transaction_on_connection(
    connection: sqlite3.Connection,
    customer_id: int,
    amount: int,
    transaction_type: str,
    description: str | None,
) -> int:
    transaction = TransactionCreate.model_validate(
        {
            "customer_id": customer_id,
            "transaction_type": transaction_type,
            "amount": amount,
            "description": description,
        },
        strict=True,
    )

    _require_customer(connection, transaction.customer_id)
    cursor = connection.execute(
        """
        INSERT INTO transactions (customer_id, transaction_type, amount, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            transaction.customer_id,
            transaction.transaction_type,
            transaction.amount,
            transaction.description,
        ),
    )
    return int(cursor.lastrowid)


def _add_transaction(
    customer_id: int,
    amount: int,
    transaction_type: str,
    description: str | None,
) -> int:
    with closing(get_connection()) as connection, connection:
        return _add_transaction_on_connection(
            connection,
            customer_id,
            amount,
            transaction_type,
            description,
        )


def add_customer(name: str) -> int:
    trimmed_name = CustomerCreate(name=name).name
    normalized_name = " ".join(trimmed_name.lower().split())
    with closing(get_connection()) as connection, connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO customers (name, normalized_name)
                VALUES (?, ?)
                """,
                (trimmed_name, normalized_name),
            )
        except sqlite3.IntegrityError as error:
            existing = connection.execute(
                "SELECT 1 FROM customers WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    f"Customer already exists: {normalized_name}"
                ) from error
            raise
        return int(cursor.lastrowid)


def add_credit(
    customer_id: int, amount: int, description: str | None = None
) -> int:
    return _add_transaction(customer_id, amount, "credit", description)


def add_payment(
    customer_id: int, amount: int, description: str | None = None
) -> int:
    return _add_transaction(customer_id, amount, "payment", description)


def get_transaction(transaction_id: int) -> dict:
    _validate_positive_integer(transaction_id, "transaction_id")
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT id, customer_id, transaction_type, amount, description,
                   created_at, is_voided
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown transaction ID: {transaction_id}")
    return dict(
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
            row,
        )
    )


def _get_balance_on_connection(
    connection: sqlite3.Connection,
    customer_id: int,
) -> int:
    _validate_positive_integer(customer_id, "customer_id")
    _require_customer(connection, customer_id)
    row = connection.execute(
        """
        SELECT COALESCE(
            SUM(
                CASE transaction_type
                    WHEN 'credit' THEN amount
                    WHEN 'payment' THEN -amount
                END
            ),
            0
        )
        FROM transactions
        WHERE customer_id = ? AND is_voided = 0
        """,
        (customer_id,),
    ).fetchone()
    return int(row[0])


def list_customers() -> list[dict]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            "SELECT id, name, created_at FROM customers ORDER BY id ASC"
        ).fetchall()
    return [
        dict(zip(("id", "name", "created_at"), row))
        for row in rows
    ]


def get_balance(customer_id: int) -> int:
    with closing(get_connection()) as connection, connection:
        return _get_balance_on_connection(connection, customer_id)


def get_customer_ledger(customer_id: int) -> list[dict]:
    _validate_positive_integer(customer_id, "customer_id")
    with closing(get_connection()) as connection, connection:
        _require_customer(connection, customer_id)
        rows = connection.execute(
            """
            SELECT id, transaction_type, amount, description, created_at, is_voided
            FROM transactions
            WHERE customer_id = ?
            ORDER BY id ASC
            """,
            (customer_id,),
        ).fetchall()
        columns = (
            "id",
            "transaction_type",
            "amount",
            "description",
            "created_at",
            "is_voided",
        )
        return [dict(zip(columns, row)) for row in rows]


def void_last(customer_id: int) -> int:
    _validate_positive_integer(customer_id, "customer_id")
    with closing(get_connection()) as connection, connection:
        _require_customer(connection, customer_id)
        row = connection.execute(
            """
            SELECT id
            FROM transactions
            WHERE customer_id = ? AND is_voided = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No non-voided transactions for customer ID: {customer_id}")

        transaction_id = int(row[0])
        connection.execute(
            "UPDATE transactions SET is_voided = 1 WHERE id = ?",
            (transaction_id,),
        )
        return transaction_id


def daily_summary() -> dict[str, int]:
    with closing(get_connection()) as connection, connection:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'credit' THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN transaction_type = 'payment' THEN amount ELSE 0 END), 0),
                COUNT(*)
            FROM transactions
            WHERE is_voided = 0
              AND date(created_at, 'localtime') = date('now', 'localtime')
            """
        ).fetchone()
        return {
            "total_credits": int(row[0]),
            "total_payments": int(row[1]),
            "transaction_count": int(row[2]),
        }

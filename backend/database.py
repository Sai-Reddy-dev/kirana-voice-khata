from contextlib import closing
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "kirana.db"


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with closing(get_connection()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                transaction_type TEXT NOT NULL
                    CHECK (transaction_type IN ('credit', 'payment')),
                amount INTEGER NOT NULL CHECK (amount > 0),
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_voided INTEGER NOT NULL DEFAULT 0
                    CHECK (is_voided IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS pending_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id),
                transaction_type TEXT
                    CHECK (transaction_type IN ('credit', 'payment')),
                amount INTEGER CHECK (amount > 0),
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_customer_id
                ON transactions(customer_id);
            CREATE INDEX IF NOT EXISTS idx_pending_entries_customer_id
                ON pending_entries(customer_id);
            """
        )

from contextlib import closing
import json
import os
import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "kirana.db"
)
DATABASE_PATH = Path(os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH)


def get_connection() -> sqlite3.Connection:
    configured_path = os.getenv("DATABASE_PATH")
    database_path = Path(configured_path) if configured_path else DATABASE_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with closing(get_connection()) as connection, connection:
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'confirmed', 'expired')),
                extraction_json TEXT,
                candidate_customer_ids_json TEXT NOT NULL DEFAULT '[]',
                cancelled_at TEXT,
                interaction_state TEXT NOT NULL DEFAULT 'transaction_confirmation'
                    CHECK (interaction_state IN (
                        'transaction_confirmation',
                        'customer_creation_confirmation',
                        'customer_created'
                    )),
                resumed_pending_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_customer_id
                ON transactions(customer_id);
            CREATE INDEX IF NOT EXISTS idx_pending_entries_customer_id
                ON pending_entries(customer_id);
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(pending_entries)")
        }
        migrations = {
            "status": (
                "ALTER TABLE pending_entries ADD COLUMN status TEXT NOT NULL "
                "DEFAULT 'pending' CHECK "
                "(status IN ('pending', 'processing', 'confirmed', 'expired'))"
            ),
            "extraction_json": (
                "ALTER TABLE pending_entries ADD COLUMN extraction_json TEXT"
            ),
            "candidate_customer_ids_json": (
                "ALTER TABLE pending_entries ADD COLUMN "
                "candidate_customer_ids_json TEXT NOT NULL DEFAULT '[]'"
            ),
            "cancelled_at": (
                "ALTER TABLE pending_entries ADD COLUMN cancelled_at TEXT"
            ),
            "interaction_state": (
                "ALTER TABLE pending_entries ADD COLUMN interaction_state TEXT "
                "NOT NULL DEFAULT 'transaction_confirmation' CHECK "
                "(interaction_state IN ('transaction_confirmation', "
                "'customer_creation_confirmation', 'customer_created'))"
            ),
            "resumed_pending_id": (
                "ALTER TABLE pending_entries ADD COLUMN resumed_pending_id INTEGER"
            ),
        }
        for column, statement in migrations.items():
            if column not in columns:
                connection.execute(statement)

        legacy_entries = connection.execute(
            """
            SELECT id, description
            FROM pending_entries
            WHERE extraction_json IS NULL AND description IS NOT NULL
            """
        ).fetchall()
        for entry_id, stored_description in legacy_entries:
            try:
                wrapper = json.loads(stored_description)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(wrapper, dict) or not isinstance(
                wrapper.get("extraction"), dict
            ):
                continue
            connection.execute(
                """
                UPDATE pending_entries
                SET description = ?, extraction_json = ?
                WHERE id = ? AND extraction_json IS NULL
                """,
                (
                    wrapper.get("description"),
                    json.dumps(wrapper["extraction"], ensure_ascii=False),
                    entry_id,
                ),
            )
        matched_entries = connection.execute(
            """
            SELECT id, customer_id FROM pending_entries
            WHERE customer_id IS NOT NULL
              AND candidate_customer_ids_json = '[]'
            """
        ).fetchall()
        for entry_id, customer_id in matched_entries:
            connection.execute(
                """
                UPDATE pending_entries
                SET candidate_customer_ids_json = ?
                WHERE id = ?
                """,
                (json.dumps([customer_id]), entry_id),
            )

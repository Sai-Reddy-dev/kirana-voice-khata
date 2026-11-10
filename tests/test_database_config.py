from contextlib import closing
from pathlib import Path

import pytest

from backend import database


def _database_filename() -> str:
    with closing(database.get_connection()) as connection:
        return connection.execute("PRAGMA database_list").fetchone()[2]


def test_database_path_defaults_to_existing_local_path() -> None:
    expected = Path(__file__).resolve().parent.parent / "data" / "kirana.db"

    assert database.DEFAULT_DATABASE_PATH == expected


def test_unconfigured_database_uses_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_path = tmp_path / "local" / "kirana.db"
    monkeypatch.setattr(database, "DATABASE_PATH", default_path)
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    database.init_db()

    assert Path(_database_filename()) == default_path


def test_configured_database_path_is_created_and_initialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_path = tmp_path / "persistent" / "kirana.db"
    monkeypatch.setenv("DATABASE_PATH", str(configured_path))

    database.init_db()

    assert configured_path.is_file()
    assert Path(_database_filename()) == configured_path
    with closing(database.get_connection()) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"customers", "transactions", "pending_entries"} <= table_names


def test_database_initialization_preserves_existing_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_path = tmp_path / "persistent" / "kirana.db"
    monkeypatch.setenv("DATABASE_PATH", str(configured_path))
    database.init_db()
    with closing(database.get_connection()) as connection, connection:
        connection.execute(
            "INSERT INTO customers (name, normalized_name) VALUES (?, ?)",
            ("Fictional Customer", "fictional customer"),
        )

    database.init_db()

    with closing(database.get_connection()) as connection:
        assert connection.execute(
            "SELECT name FROM customers"
        ).fetchone()[0] == "Fictional Customer"

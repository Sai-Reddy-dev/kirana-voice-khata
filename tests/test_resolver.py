import pytest

from backend import database, ledger
from backend.resolver import normalize_customer_name, resolve_customer


@pytest.fixture
def temporary_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "kirana_test.db")
    database.init_db()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Ramesh anna", "ramesh"),
        ("Suresh garu", "suresh"),
        ("  Ramesh   Kumar  ", "ramesh kumar"),
        ("", ""),
        ("   ", ""),
        ("anna", ""),
        ("  garu   ", ""),
    ],
)
def test_normalize_customer_name(
    temporary_database, name: str, expected: str
) -> None:
    assert normalize_customer_name(name) == expected


def test_resolve_exact_customer(temporary_database) -> None:
    customer_id = ledger.add_customer("Ramesh")

    result = resolve_customer("Ramesh")

    assert result == {
        "status": "matched",
        "matches": [
            {
                "customer_id": customer_id,
                "customer_name": "Ramesh",
                "score": 100.0,
            }
        ],
    }


def test_resolve_customer_with_honorific(temporary_database) -> None:
    customer_id = ledger.add_customer("Ramesh")

    result = resolve_customer("Ramesh anna")

    assert result["status"] == "matched"
    assert result["matches"][0]["customer_id"] == customer_id


def test_resolve_similar_customers_as_multiple_matches(temporary_database) -> None:
    ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")

    result = resolve_customer("Suresh")

    assert result["status"] == "multiple_matches"
    assert [match["customer_name"] for match in result["matches"]] == [
        "Suresh Kumar",
        "Suresh Reddy",
    ]


def test_unknown_customer_returns_not_found(temporary_database) -> None:
    ledger.add_customer("Ramesh")

    assert resolve_customer("Unknown Person") == {
        "status": "not_found",
        "matches": [],
    }


def test_empty_customer_name_returns_not_found(temporary_database) -> None:
    assert resolve_customer("") == {"status": "not_found", "matches": []}


@pytest.mark.parametrize("threshold", [-1, 101, True, 75.5])
def test_invalid_threshold_raises_value_error(
    temporary_database, threshold
) -> None:
    with pytest.raises(ValueError):
        resolve_customer("Ramesh", threshold=threshold)


def test_multiple_matches_are_sorted_by_descending_score(
    temporary_database,
) -> None:
    ledger.add_customer("Suresh Kumar")
    ledger.add_customer("Suresh Reddy")

    matches = resolve_customer("Suresh Kumar", threshold=0)["matches"]

    assert len(matches) == 2
    assert [match["score"] for match in matches] == sorted(
        (match["score"] for match in matches), reverse=True
    )

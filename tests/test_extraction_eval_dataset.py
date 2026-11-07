from pathlib import Path

from scripts.evaluate_extraction import calculate_metrics, load_dataset


DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "extraction_eval.jsonl"
)


def test_extraction_evaluation_dataset_covers_all_intents_and_safe_amounts() -> None:
    cases = load_dataset(DATASET_PATH)

    assert len(cases) >= 30
    assert {
        case["expected"]["intent"] for case in cases
    } == {
        "add_credit",
        "add_payment",
        "check_balance",
        "daily_summary",
        "undo_last",
        "unknown",
    }
    assert all(
        case["expected"]["amount"] is None
        for case in cases
        if case["expected"]["amount_ambiguous"]
    )


def test_scoring_uses_requested_denominators_and_ambiguous_safety() -> None:
    cases = [
        {
            "expected": {
                "intent": "add_credit",
                "customer_name": "Asha",
                "amount": None,
                "amount_ambiguous": True,
            }
        },
        {
            "expected": {
                "intent": "add_payment",
                "customer_name": None,
                "amount": None,
                "amount_ambiguous": False,
            }
        },
        {
            "expected": {
                "intent": "check_balance",
                "customer_name": "Ravi",
                "amount": None,
                "amount_ambiguous": False,
            }
        },
        {
            "expected": {
                "intent": "daily_summary",
                "customer_name": None,
                "amount": None,
                "amount_ambiguous": False,
            }
        },
        {
            "expected": {
                "intent": "undo_last",
                "customer_name": None,
                "amount": None,
                "amount_ambiguous": False,
            }
        },
    ]
    actuals = [
        {
            "intent": "add_credit",
            "customer_name": "Asha",
            "amount": 200,
            "amount_ambiguous": False,
        },
        {
            "intent": "add_payment",
            "customer_name": "Unknown",
            "amount": None,
            "amount_ambiguous": False,
        },
        {
            "intent": "check_balance",
            "customer_name": "Ravi",
            "amount": 10,
            "amount_ambiguous": False,
        },
        {
            "intent": "daily_summary",
            "customer_name": None,
            "amount": None,
            "amount_ambiguous": False,
        },
        {
            "intent": "undo_last",
            "customer_name": None,
            "amount": None,
            "amount_ambiguous": False,
        },
    ]

    metrics = calculate_metrics(cases, actuals)

    assert metrics["intent"] == {"correct": 5, "total": 5}
    assert metrics["customer_name"] == {"correct": 2, "total": 2}
    assert metrics["null_customer"] == {"correct": 2, "total": 3}
    assert metrics["amount"] == {"correct": 1, "total": 2}
    assert metrics["exact_match"] == {"correct": 2, "total": 5}
    assert metrics["ambiguous_amount_safety"] == {"correct": 0, "total": 1}


def test_ambiguous_amount_safety_requires_null_and_ambiguous_flag() -> None:
    case = {
        "expected": {
            "intent": "add_credit",
            "customer_name": "Asha",
            "amount": None,
            "amount_ambiguous": True,
        }
    }
    actual = {
        "intent": "add_credit",
        "customer_name": "Asha",
        "amount": None,
        "amount_ambiguous": True,
    }

    metrics = calculate_metrics([case], [actual])

    assert metrics["ambiguous_amount_safety"] == {"correct": 1, "total": 1}
    actual["amount"] = 200
    metrics = calculate_metrics([case], [actual])
    assert metrics["ambiguous_amount_safety"] == {"correct": 0, "total": 1}

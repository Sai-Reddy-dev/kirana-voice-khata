import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.extractor import extract_transaction
from backend.models import TransactionExtraction


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATASET = _PROJECT_ROOT / "data" / "extraction_eval.jsonl"


def load_dataset(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as dataset_file:
            for line_number, line in enumerate(dataset_file, start=1):
                if not line.strip():
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid JSON on line {line_number} of {path}"
                    ) from error
                if not isinstance(case, dict):
                    raise ValueError(
                        f"Dataset line {line_number} must contain a JSON object"
                    )
                if not isinstance(case.get("case_id"), str):
                    raise ValueError(
                        f"Dataset line {line_number} is missing a string case_id"
                    )
                if not isinstance(case.get("utterance"), str):
                    raise ValueError(
                        f"Dataset case {case['case_id']} is missing a string utterance"
                    )
                try:
                    expected = TransactionExtraction.model_validate(
                        case.get("expected")
                    )
                except ValidationError as error:
                    raise ValueError(
                        f"Invalid expected extraction for case {case['case_id']}"
                    ) from error
                case["expected"] = expected.model_dump(mode="json")
                cases.append(case)
    except OSError as error:
        raise ValueError(f"Cannot read evaluation dataset {path}: {error}") from error

    if not cases:
        raise ValueError(f"Evaluation dataset is empty: {path}")
    return cases


_TRANSACTION_INTENTS = {"add_credit", "add_payment"}


def calculate_metrics(
    cases: list[dict[str, Any]], actuals: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    if len(cases) != len(actuals):
        raise ValueError("cases and actuals must have the same length")

    metrics = {
        "intent": {"correct": 0, "total": len(cases)},
        "customer_name": {"correct": 0, "total": 0},
        "null_customer": {"correct": 0, "total": 0},
        "amount": {"correct": 0, "total": 0},
        "exact_match": {"correct": 0, "total": len(cases)},
        "ambiguous_amount_safety": {"correct": 0, "total": 0},
    }

    for case, actual in zip(cases, actuals):
        expected = case["expected"]
        metrics["intent"]["correct"] += expected["intent"] == actual["intent"]
        metrics["exact_match"]["correct"] += expected == actual

        expected_customer = expected["customer_name"]
        if expected_customer is None:
            metrics["null_customer"]["total"] += 1
            metrics["null_customer"]["correct"] += actual["customer_name"] is None
        else:
            metrics["customer_name"]["total"] += 1
            metrics["customer_name"]["correct"] += (
                expected_customer == actual["customer_name"]
            )

        if expected["intent"] in _TRANSACTION_INTENTS:
            metrics["amount"]["total"] += 1
            metrics["amount"]["correct"] += (
                expected["amount"] == actual["amount"]
                and expected["amount_ambiguous"] == actual["amount_ambiguous"]
            )

        if expected["amount_ambiguous"]:
            metrics["ambiguous_amount_safety"]["total"] += 1
            metrics["ambiguous_amount_safety"]["correct"] += (
                actual["amount"] is None and actual["amount_ambiguous"] is True
            )

    return metrics


def evaluate(cases: list[dict[str, Any]]) -> int:
    actuals: list[dict[str, Any]] = []
    failures: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for case in cases:
        try:
            actual = extract_transaction(case["utterance"]).model_dump(mode="json")
        except Exception as error:
            print(
                f"Evaluation aborted at case {case['case_id']!r} "
                f"({case['utterance']}): {error}",
                file=sys.stderr,
            )
            print(
                "Check GEMINI_API_KEY, network access, and Gemini service status; "
                "no partial accuracy scores are reported.",
                file=sys.stderr,
            )
            return 1

        actuals.append(actual)
        if case["expected"] != actual:
            failures.append((case, actual))

    metrics = calculate_metrics(cases, actuals)
    print(f"Cases evaluated: {len(cases)}")
    _print_metric("Intent accuracy", metrics["intent"])
    _print_metric("Customer-name accuracy (expected non-null)", metrics["customer_name"])
    _print_metric("Null-customer correctness (expected null)", metrics["null_customer"])
    _print_metric(
        "Amount accuracy (add_credit/add_payment; amount and ambiguity flag)",
        metrics["amount"],
    )
    _print_metric(
        "Overall exact-match accuracy (all extraction fields)",
        metrics["exact_match"],
    )
    _print_metric(
        "Ambiguous-amount safety (actual amount null and ambiguous)",
        metrics["ambiguous_amount_safety"],
    )

    if failures:
        print(f"\nFailed utterances ({len(failures)}):")
        for case, actual in failures:
            print(f"\n[{case['case_id']}] {case['utterance']}")
            print(
                "Expected: "
                + json.dumps(case["expected"], ensure_ascii=False, sort_keys=True)
            )
            print(
                "Actual:   "
                + json.dumps(actual, ensure_ascii=False, sort_keys=True)
            )
    else:
        print("\nAll utterances matched exactly.")
    return 0


def _percentage(correct: int, total: int) -> str:
    if total == 0:
        return "0/0 (n/a)"
    return f"{correct}/{total} ({correct / total:.1%})"


def _print_metric(label: str, metric: dict[str, int]) -> None:
    print(f"{label}: {_percentage(metric['correct'], metric['total'])}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Gemini extraction against a labeled JSONL dataset."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_DEFAULT_DATASET,
        help=f"JSONL dataset path (default: {_DEFAULT_DATASET})",
    )
    args = parser.parse_args()

    try:
        cases = load_dataset(args.dataset)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    return evaluate(cases)


if __name__ == "__main__":
    raise SystemExit(main())

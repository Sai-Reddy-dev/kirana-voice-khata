import pytest
from pydantic import ValidationError

from backend.models import Item, TransactionExtraction


def _extraction(**overrides: object) -> TransactionExtraction:
    data: dict[str, object] = {
        "intent": "add_credit",
        "confidence": "high",
        "amount": 100,
        "items": [{"name": "rice", "quantity": 2}],
    }
    data.update(overrides)
    return TransactionExtraction.model_validate(data)


def test_positive_amount_and_quantity_are_accepted() -> None:
    result = _extraction()

    assert result.amount == 100
    assert result.items[0].quantity == 2


@pytest.mark.parametrize("amount", [0, -1])
def test_nonpositive_amount_is_rejected(amount: int) -> None:
    with pytest.raises(ValidationError):
        _extraction(amount=amount)


@pytest.mark.parametrize("quantity", [0, -1])
def test_nonpositive_quantity_is_rejected(quantity: int) -> None:
    with pytest.raises(ValidationError):
        Item(name="rice", quantity=quantity)


def test_null_amount_and_quantity_are_accepted() -> None:
    result = _extraction(amount=None, items=[{"name": "rice", "quantity": None}])

    assert result.amount is None
    assert result.items[0].quantity is None


def test_amount_and_quantity_json_schema_has_no_exclusive_minimum() -> None:
    schema = TransactionExtraction.model_json_schema()

    assert "exclusiveMinimum" not in schema["properties"]["amount"]
    assert "exclusiveMinimum" not in schema["$defs"]["Item"]["properties"]["quantity"]

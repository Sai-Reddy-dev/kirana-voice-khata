import pytest

from backend.numbers import parse_telugu_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("రెండు వందల", 200),
        ("నూట యాభై", 150),
        ("ఏడు వందల యాభై", 750),
        ("మూడు వందల", 300),
        ("వెయ్యి", 1000),
        ("రెండు వందల యాభై", 250),
        ("ఐదు వందల", 500),
        ("పన్నెండు వందల", 1200),
        ("500", 500),
        ("1200", 1200),
        ("1,200", 1200),
        ("12,345", 12345),
        ("₹1,200", 1200),
        ("250 రూపాయలు", 250),
        ("రెండు వందల రూపాయలు", 200),
        ("₹రెండు వందల", 200),
        ("  250  ", 250),
        ("  రెండు   వందల  ", 200),
        ("12,00", None),
        ("1,20,000", None),
        ("1,,200", None),
        ("నలభై", None),
        ("రెండు వేల", None),
        ("రెండు వందలలా లేదా ఐదు వందలలా", None),
        ("200 లేదా 500", None),
        ("2 kilo biyyam", None),
        ("రమేష్ కి 250 రూపాయలు సరుకు రాసుకో", None),
        ("", None),
    ],
)
def test_parse_telugu_number(text: str, expected: int | None) -> None:
    assert parse_telugu_number(text) == expected

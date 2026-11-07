import re


_TELUGU_AMOUNTS = {
    "రెండు వందల": 200,
    "నూట యాభై": 150,
    "ఏడు వందల యాభై": 750,
    "మూడు వందల": 300,
    "వెయ్యి": 1000,
    "రెండు వందల యాభై": 250,
    "ఐదు వందల": 500,
    "పన్నెండు వందల": 1200,
}
_DIGIT_AMOUNT = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)")
_CURRENCY_SUFFIX = re.compile(r" (?:రూపాయి|రూపాయలు|రూపాయల)$")


def parse_telugu_number(text: str) -> int | None:
    normalized = " ".join(text.split())
    if not normalized:
        return None

    if normalized.startswith("₹"):
        normalized = normalized[1:].strip()

    normalized = _CURRENCY_SUFFIX.sub("", normalized)
    if not normalized:
        return None

    amount = _TELUGU_AMOUNTS.get(normalized)
    if amount is not None:
        return amount

    if _DIGIT_AMOUNT.fullmatch(normalized) is None:
        return None

    amount = int(normalized.replace(",", ""))
    return amount if amount > 0 else None

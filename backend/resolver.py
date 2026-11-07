from contextlib import closing

from rapidfuzz import fuzz, process

from .database import get_connection


_HONORIFICS = {"anna", "akka", "garu", "bhai", "ji", "sir"}


def normalize_customer_name(name: str) -> str:
    words = name.lower().split()
    while words and words[-1] in _HONORIFICS:
        words.pop()
    return " ".join(words)


def resolve_customer(name: str, threshold: int = 75) -> dict:
    if (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or not 0 <= threshold <= 100
    ):
        raise ValueError("threshold must be an integer between 0 and 100")

    normalized_name = normalize_customer_name(name)
    if not normalized_name:
        return {"status": "not_found", "matches": []}

    with closing(get_connection()) as connection:
        customers = connection.execute(
            "SELECT id, name, normalized_name FROM customers"
        ).fetchall()

    if not customers:
        return {"status": "not_found", "matches": []}

    choices = [normalize_customer_name(customer[2]) for customer in customers]
    fuzzy_matches = process.extract(
        normalized_name,
        choices,
        scorer=fuzz.ratio,
        limit=None,
    )
    all_matches = [
        {
            "customer_id": int(customers[index][0]),
            "customer_name": customers[index][1],
            "score": score,
        }
        for _, score, index in fuzzy_matches
    ]
    all_matches.sort(key=lambda match: (-match["score"], match["customer_id"]))
    matches = [match for match in all_matches if match["score"] >= threshold]
    close_top_candidates = (
        len(all_matches) >= 2
        and all_matches[0]["score"] >= 60
        and all_matches[1]["score"] >= 60
        and all_matches[0]["score"] - all_matches[1]["score"] <= 10
    )

    if close_top_candidates:
        highest_score = all_matches[0]["score"]
        matches = [
            match
            for match in all_matches
            if match["score"] >= 60 and highest_score - match["score"] <= 10
        ]
        status = "multiple_matches"
    elif not matches:
        status = "not_found"
    elif len(matches) > 1:
        status = "multiple_matches"
    else:
        status = "matched"

    return {"status": status, "matches": matches}

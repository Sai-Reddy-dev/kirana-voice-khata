# Gemini Extraction Evaluation

The labeled dataset is `data/extraction_eval.jsonl`. It contains 36 utterances,
balanced across the six extraction intents, with Telugu script, transliteration,
mixed Telugu-English, number words, digit amounts, missing amounts, ambiguous
amounts, and item quantities.

Run the evaluation explicitly from the repository root after setting
`GEMINI_API_KEY` in `.env`:

```powershell
python -m scripts.evaluate_extraction
```

To evaluate a different JSONL file:

```powershell
python -m scripts.evaluate_extraction --dataset path\to\dataset.jsonl
```

This script calls the real Gemini extractor once per utterance; it can incur
API usage and requires working credentials, network access, and an available
Gemini service. It is intentionally not called by pytest. The extractor's
configured retry for invalid model output may make a second request for an
utterance.

The evaluation reports intent accuracy over every case. Customer-name accuracy
uses only cases where a customer name is expected; null-customer correctness is
reported separately over cases where the expected name is null. Amount accuracy
uses `add_credit` and `add_payment` cases only, including cases with a missing
or ambiguous expected amount, and requires both `amount` and
`amount_ambiguous` to match. `check_balance`, `daily_summary`, and `undo_last`
are excluded from amount accuracy. The separate ambiguous-amount safety metric
uses all cases expected to be ambiguous and counts success only when the actual
amount is null and `amount_ambiguous` is true.

Every metric prints its correct/total numerator and denominator (and percentage;
an empty denominator is shown as `0/0 (n/a)`). Overall exact match uses all
cases and compares every `TransactionExtraction` field, including items,
confidence, and description. Every exact-match failure prints its utterance
and full expected and actual outputs.

If credentials are missing, the network is unavailable, or Gemini returns an
API error, the script reports the case where evaluation stopped and exits
without presenting partial accuracy scores. Check `.env`, connectivity, and
Gemini service status, then rerun the evaluation explicitly. A malformed
dataset is reported before any model calls begin.

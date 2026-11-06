# Model Evaluation Results

## Phase 1 — Telugu Speech-to-Text (Gnani Prisma)

### Test Configuration
- **Provider:** Gnani
- **Model:** Prisma v3.0
- **Endpoint:** `/stt/v3`
- **Language parameter:** `indic-auto`
- **Audio sample rate:** 16 kHz
- **Audio format:** WAV
- **Test language:** Telugu (`te-IN`)
- **Environment:** Room recording with fan and some outside/background sounds

### Results Summary
- **Total utterances tested:** 10
- **Successful API responses:** 10/10 (HTTP 200)
- **Telugu recognition:** 10/10 sentences recognized in Telugu
- **Observed end-to-end latency:** Approximately 150–185 ms in reported tests
- **Initial language detection issue:** A short greeting was initially detected as Gujarati (`gu-IN`). A clear Telugu sentence was subsequently detected as `te-IN`.

### Utterance Results

| # | Expected Utterance | Recognized Transcript | Result |
|---|---|---|---|
| 1 | రాము దగ్గర నుంచి 500 రూపాయలు తీసుకున్నాను | రాము దగ్గర నుంచి ఐదు వందల రూపాయలు తీసుకున్నాను. | Correct meaning; number normalized to words |
| 2 | రాము దగ్గర 200 రూపాయలు బాకీ ఉంది | రాము దగ్గర రెండు వందల రూపాయలు బాకీ ఉంది. | Correct |
| 3 | సీతకు 150 రూపాయలు ఇచ్చాను | సీతకు నూట యాభై రూపాయలు ఇచ్చాను. | Correct |
| 4 | కిరాణా సరుకులు 750 రూపాయలు అయ్యాయి | కిరాణా సరుకులు ఏడు వందల యాభై రూపాయలు అయ్యాయి. | Correct |
| 5 | నిన్న ఇచ్చిన డబ్బులో 300 రూపాయలు తిరిగి ఇచ్చాడు | నిన్న ఇచ్చిన డబ్బుల్లో మూడు వందల రూపాయలు తిరిగి ఇచ్చాడు. | Meaning preserved |
| 6 | మోహన్ దగ్గర వెయ్యి రూపాయలు బాకీ ఉంది | మోహన్ దగ్గర వెయ్యి రూపాయలు బాకీ ఉంది. | Correct |
| 7 | ఈరోజు 250 రూపాయల సరుకులు ఇచ్చాను | ఈరోజు రెండు వందల యాభై రూపాయల సరుకులు ఇచ్చాను. | Correct |
| 8 | రవి 500 రూపాయలు చెల్లించాడు | రవి ఐదు వందల రూపాయలు చెల్లించాడు. | Correct |
| 9 | లక్ష్మి దగ్గర 1200 రూపాయలు తీసుకున్నాను | లక్ష్మి దగ్గర పన్నెండు వందల రూపాయలు తీసుకున్నాను. | Correct |
| 10 | రమేష్ ఖాతాలో 400 రూపాయలు జమ చేయి | రమేష్ ఖాతాలో రెండు వందల యాభై రూపాయలు జమ చేయి. | **Mismatch — expected 400, recognized 250** |

### Observations
- Telugu speech was recognized consistently across the sample.
- Customer names and common transaction vocabulary were generally recognized correctly.
- Numeric normalization to Telugu words occurred.
- Background fan and outdoor sounds were present during testing; this was an informal test, not a controlled noise benchmark.
- One amount mismatch occurred in utterance 10 and must be investigated.

### Conclusion
Gnani Prisma v3.0 is suitable to continue prototyping Telugu STT integration. Further testing is required for numeric accuracy, noisy conditions, and broader utterance coverage.

## Gemini Transcript Extraction Evaluation

### Test Results

| Test scenario | Result |
|---|---|
| Money taken from customer | PASS |
| Customer repayment | PASS |
| Goods explicitly given on credit | PASS |
| Money lent to customer | PASS |
| Existing outstanding balance | PASS |
| Balance inquiry | PASS |
| Multiple product extraction | PASS after prompt correction |
| Missing amount | PASS |
| Ambiguous goods transaction | PASS after prompt correction |
| Telugu number extraction (₹1,200) | PASS |

### Prompt Improvements

- Corrected transaction direction for `loan_taken`.
- Explicitly classified existing balance statements as `unknown`.
- Added extraction rules for multiple products.
- Required explicit credit wording before classifying as `credit_given`.
- Used amount `0` when no amount was stated.

### Evaluation Summary

Gemini successfully extracted structured JSON for the tested Telugu transaction scenarios. Customer names, amounts, transaction types, and product names were generally correct.

Two prompt weaknesses were discovered and corrected during testing:
1. Multiple products were not initially extracted completely.
2. Goods given without explicit credit wording were incorrectly classified as credit.

These corrections improved extraction behavior.

**Status:** Suitable for prototype development. Broader testing with additional Telugu dialects, ambiguous speech, and real STT transcripts remains necessary.


@'
# Gnani Prisma STT
PRISMA_API_KEY=
PRISMA_BASE_URL=https://api.vachana.ai/stt/v3

# Gnani Timbre TTS
TIMBRE_API_KEY=
TIMBRE_BASE_URL=https://api.vachana.ai/api/v1/tts/inference

# Gemini API
GEMINI_API_KEY=
'@ | Set-Content .env.example -Encoding utf8

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing in .env")

client = genai.Client(api_key=API_KEY)

transcript = "లక్ష్మి దగ్గర నుంచి పన్నెండు వందల రూపాయలు తీసుకున్నాను."


prompt = f"""
You are a transaction extraction engine for a Telugu kirana shop ledger.

Read the Telugu transcript carefully. Extract the customer, amount,
transaction type, and items.

TRANSACTION TYPE RULES:

1. loan_taken:
   The shopkeeper explicitly took money FROM the customer.
   Telugu example: "రాము దగ్గర నుంచి 500 రూపాయలు తీసుకున్నాను"
   Meaning: I took 500 rupees from Ramu.

2. payment_received:
   The customer paid money TO the shopkeeper.
   Telugu example: "రాము 500 రూపాయలు చెల్లించాడు"
   Meaning: Ramu paid 500 rupees.

3. credit_given:
   The shopkeeper gave goods to the customer on credit.
   Telugu example: "రాముకు 500 రూపాయల సరుకులు ఇచ్చాను"
   Meaning: I gave Ramu goods worth 500 rupees on credit.

4. loan_given:
   The shopkeeper explicitly lent money TO the customer.
   Telugu example: "రాముకు 500 రూపాయలు అప్పుగా ఇచ్చాను"
   Meaning: I lent Ramu 500 rupees.

5. unknown:
   Use when the transaction direction or meaning is unclear.

6. unknown:
   Use for balance statements or questions that do not describe a new transaction.
   Telugu examples:
   "రాము దగ్గర 200 రూపాయలు బాకీ ఉంది"
   "రాము ఎంత బాకీ ఉన్నాడు"
   These describe an existing balance, not a new transaction.
IMPORTANT:
- "దగ్గర నుంచి తీసుకున్నాను" means money taken FROM that person.
- "చెల్లించాడు" means the customer paid the shopkeeper.
- "సరుకులు ఇచ్చాను" means goods were given; determine credit only if context supports it.
- Never confuse money received as a loan with customer repayment.
- Extract amount as an integer number of rupees.
- Do not calculate balances.
- Do not invent missing information.
- "బాకీ ఉంది" alone describes an existing outstanding balance.
  Do not classify it as credit_given unless the transcript explicitly
  describes goods or money newly given on credit.
  - "సరుకులు ఇచ్చాను" alone does NOT prove credit.
- Classify as credit_given only when credit is explicitly stated
  (for example, "బాకీకి ఇచ్చాను").
- If goods were given but payment/credit status is unclear,
  use unknown.

Transcript:
{transcript}
"""


schema = {
    "type": "OBJECT",
    "properties": {
        "customer_name": {"type": "STRING"},
        "amount_rupees": {"type": "INTEGER"},
        "transaction_type": {
            "type": "STRING",
            "enum": [
                "credit_given",
                "payment_received",
                "loan_taken",
                "loan_given",
                "unknown"
            ]
        },
        "items": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": [
        "customer_name",
        "amount_rupees",
        "transaction_type",
        "items"
    ]
}

print("Sending Telugu transcript to Gemini...")

response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        temperature=0,
    ),
)

print("Gemini response:")
print(response.text)
print("Parsed output:")
print(response.parsed)

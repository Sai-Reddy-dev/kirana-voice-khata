import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import ValidationError

from .models import TransactionExtraction


_MODEL = "gemini-3.5-flash"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "extract_system.txt"
_DOTENV_PATH = _PROJECT_ROOT / ".env"


def extract_transaction(transcript: str) -> TransactionExtraction:
    if not transcript.strip():
        raise ValueError("transcript must not be blank")

    load_dotenv(dotenv_path=_DOTENV_PATH)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from .env or environment")

    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    try:
        client = genai.Client(api_key=api_key)
    except Exception as error:
        raise RuntimeError("Gemini transaction extraction request failed") from error

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=_MODEL,
                contents=transcript.strip(),
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=TransactionExtraction,
                    temperature=0,
                ),
            )
        except Exception as error:
            raise RuntimeError(
                "Gemini transaction extraction request failed"
            ) from error

        try:
            parsed: Any = response.parsed
            if parsed is None:
                response_text = response.text
                if not isinstance(response_text, str):
                    raise ValueError("Gemini returned no structured extraction response")
                try:
                    parsed = json.loads(response_text)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        "Gemini returned malformed extraction JSON"
                    ) from error

            return TransactionExtraction.model_validate(parsed)
        except (ValueError, ValidationError):
            if attempt == 1:
                return TransactionExtraction(
                    intent="unknown",
                    customer_name=None,
                    amount=None,
                    items=[],
                    confidence="low",
                    amount_ambiguous=True,
                    description=None,
                )

    raise RuntimeError("Gemini transaction extraction retry failed unexpectedly")

"""1. Normaliser — cleans line-item text and translates non-English descriptions.

Every line gets deterministic cleanup. Only receipts with non-English lines call the model, once per
receipt, and only for those lines (ADR-003, ADR-028). If translation fails, the cleaned original is
used: the classifier also sees the raw text, so a failed translation degrades gracefully.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from .llm import BudgetExceeded, LLMClient, LLMError
from .models import Receipt
from .prompts import NORMALISER_SCHEMA, NORMALISER_SYSTEM, NORMALISER_VERSION


@dataclass(frozen=True)
class NormalisedLine:
    line_id: str
    text_en: str
    translated: bool


def clean(text: str) -> str:
    """Unicode NFKC (full-width -> ASCII where equivalent) and whitespace collapse."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def normalise_receipt(receipt: Receipt, llm: LLMClient | None) -> dict[str, NormalisedLine]:
    lines = {
        item.line_id: NormalisedLine(item.line_id, clean(item.description_raw), False)
        for item in receipt.line_items
    }
    foreign = [item for item in receipt.line_items if item.language != "en"]
    if not foreign or llm is None:
        return lines

    payload = [
        {"line_id": i.line_id, "language": i.language, "text": clean(i.description_raw)}
        for i in foreign
    ]
    expected = {i.line_id for i in foreign}

    def validate(response: dict) -> dict[str, str]:
        translations = {row["line_id"]: clean(row["text_en"]) for row in response["items"]}
        if set(translations) != expected or not all(translations.values()):
            raise ValueError(f"translation lines {sorted(translations)} != {sorted(expected)}")
        return translations

    try:
        translations = llm.complete_json(
            stage="normaliser",
            prompt_version=NORMALISER_VERSION,
            system=NORMALISER_SYSTEM,
            user=json.dumps({"items": payload}, ensure_ascii=False),
            schema_name="translations",
            schema=NORMALISER_SCHEMA,
            validate=validate,
        )
    except BudgetExceeded:
        raise
    except LLMError:
        return lines  # fall back to the cleaned original text

    for line_id, text in translations.items():
        lines[line_id] = NormalisedLine(line_id, text, True)
    return lines

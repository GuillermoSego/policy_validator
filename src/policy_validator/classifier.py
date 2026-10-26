"""2. Item classifier — category, restricted flag, confidence and item facts per line item.

One model call per itemized receipt, with the receipt context (ADR-020). The model extracts facts;
`restricted` comes from the taxonomy (ADR-015). Non-itemized receipts need no model: their single
charge is `other` by definition (EXC-03). If the model fails after retries, every line falls back to
`other` with confidence 0, which raises an EXC-03 review signal instead of a guess (ADR-026).
"""

from __future__ import annotations

import json

from .data import is_restricted
from .llm import BudgetExceeded, LLMClient, LLMError
from .models import ClassifiedItem, ItemAttributes, LineItem, Receipt
from .normaliser import NormalisedLine
from .prompts import CLASSIFIER_SCHEMA, CLASSIFIER_VERSION, classifier_system

_ATTRIBUTE_FIELDS = tuple(ItemAttributes.model_fields)


def _item(
    line: LineItem,
    text_en: str,
    category: str,
    confidence: float,
    attributes: ItemAttributes,
    rationale: str,
) -> ClassifiedItem:
    return ClassifiedItem(
        line_id=line.line_id,
        description_raw=line.description_raw,
        description_en=text_en,
        category=category,
        restricted=is_restricted(category),
        confidence=min(max(confidence, 0.0), 1.0),
        attributes=attributes,
        rationale=rationale,
        quantity=line.quantity,
        unit_price_usd=line.amount_usd / line.quantity if line.quantity else line.amount_usd,
        amount_usd=line.amount_usd,
    )


def _user_message(receipt: Receipt, normalised: dict[str, NormalisedLine]) -> str:
    return json.dumps(
        {
            "receipt": {
                "merchant_name": receipt.merchant_name,
                "mcc": receipt.mcc,
                "mcc_description": receipt.mcc_description,
                "declared_expense_type": receipt.submitted_expense_type,
                "attendee_count": receipt.attendee_count,
                "currency": receipt.currency,
            },
            "items": [
                {
                    "line_id": line.line_id,
                    "text_en": normalised[line.line_id].text_en,
                    "text_original": line.description_raw,
                    "language": line.language,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                }
                for line in receipt.line_items
            ],
        },
        ensure_ascii=False,
    )


def classify_receipt(
    receipt: Receipt, normalised: dict[str, NormalisedLine], llm: LLMClient
) -> list[ClassifiedItem]:
    if not receipt.itemized:
        return [
            _item(
                line,
                normalised[line.line_id].text_en,
                "other",
                1.0,
                ItemAttributes(),
                "non-itemized charge: contents unknown",
            )
            for line in receipt.line_items
        ]

    expected = [line.line_id for line in receipt.line_items]

    def validate(response: dict) -> dict[str, dict]:
        rows = {row["line_id"]: row for row in response["items"]}
        if sorted(rows) != sorted(expected) or len(response["items"]) != len(expected):
            raise ValueError(f"classified lines {sorted(rows)} != {sorted(expected)}")
        for row in rows.values():
            is_restricted(row["category"])  # KeyError on a category outside the taxonomy
            ItemAttributes(**{k: row[k] for k in _ATTRIBUTE_FIELDS})
            float(row["confidence"])
        return rows

    try:
        rows = llm.complete_json(
            stage="classifier",
            prompt_version=CLASSIFIER_VERSION,
            system=classifier_system(),
            user=_user_message(receipt, normalised),
            schema_name="classification",
            schema=CLASSIFIER_SCHEMA,
            validate=validate,
        )
    except BudgetExceeded:
        raise
    except LLMError as exc:
        return [
            _item(
                line,
                normalised[line.line_id].text_en,
                "other",
                0.0,
                ItemAttributes(),
                f"classifier failed: {exc}"[:200],
            )
            for line in receipt.line_items
        ]

    return [
        _item(
            line,
            normalised[line.line_id].text_en,
            rows[line.line_id]["category"],
            float(rows[line.line_id]["confidence"]),
            ItemAttributes(**{k: rows[line.line_id][k] for k in _ATTRIBUTE_FIELDS}),
            rows[line.line_id]["rationale"],
        )
        for line in receipt.line_items
    ]

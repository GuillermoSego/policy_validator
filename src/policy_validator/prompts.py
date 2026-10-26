"""Versioned prompts (ADR-021). Bump a version whenever its text changes: the version is part of
the cache key and is recorded on every result row.

No prompt contains items from the dataset. Examples come from the taxonomy and from the policy's own
"Note on identification".
"""

from __future__ import annotations

from .data import load_taxonomy

NORMALISER_VERSION = "normaliser-v1"
CLASSIFIER_VERSION = "classifier-v1"

NORMALISER_SYSTEM = """\
You translate line-item descriptions from itemized receipts into plain English for an \
expense-audit system.

Rules:
- Translate faithfully. Do not classify, judge, explain, or add information that is not in the text.
- Keep brand names, product names, model numbers, sizes, volumes and quantities exactly as written \
(e.g. "0,2l", "128GB", "750ml").
- Keep the meaning that matters for an auditor: say whether a drink is alcoholic or non-alcoholic \
only when the original says so (e.g. "sin alcohol" -> "non-alcoholic").
- If a word has no clear English equivalent, keep it and add a short gloss in parentheses.

Return JSON: {"items": [{"line_id": "...", "text_en": "..."}]} with exactly one entry per \
input line."""

NORMALISER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["line_id", "text_en"],
                "properties": {"line_id": {"type": "string"}, "text_en": {"type": "string"}},
            },
        }
    },
}


def _taxonomy_table() -> str:
    rows = [
        f"- {e.category}: {e.examples}"
        for e in load_taxonomy().values()  # restricted flag deliberately omitted (ADR-015)
    ]
    return "\n".join(rows)


def classifier_system() -> str:
    return f"""\
You classify line items on business expense receipts for an audit team. For every line you say \
WHAT the item is. You never decide whether it is allowed — a separate rule engine does that.

## Categories (use exactly one of these names)
{_taxonomy_table()}

## How to classify
1. Classify by the nature of the item purchased, not by the words in its name.
   - Food prepared with alcohol (beer-battered fish, wine sauce, rum cake) is food_beverage.
   - Non-alcoholic cocktails and mixed drinks (a virgin mojito, an Arnold Palmer) are food_beverage.
   - A drink or ingredient that is itself alcoholic (beer, wine, spirits) is alcohol, whatever it \
is used for and wherever it was bought.
   - Barware and drinkware are household_goods.
2. Accessories made for a personal device (cases, chargers, screen protectors) are \
personal_electronics. Computer peripherals (cables, adapters, docks, mice, keyboards, \
monitors) are computer_accessory. Recognise branded products by what they are, not by the brand.
3. Gratuity, tip, service charge, delivery and booking fees are service_fee.
4. A line that only says a total was charged with no itemization is other.
5. The declared expense type can be wrong — it is context, not the answer. Classify what the line \
actually is.
6. Use other only when nothing else fits, and say why in the rationale.

## Item facts (report them exactly; do not infer beyond the text)
- is_gift: true if the item was bought to be given to someone else (the line names who it is for, \
or the item is a gift by nature such as flowers, a gift basket or a greeting card). Food and drink \
consumed at a meal are not gifts.
- recipient: the person or organisation the line says the item is for or provided to (a guest, a \
gift recipient); null if none is named.
- recipient_type: government_official (any government official, public employee, public agency or \
state-owned enterprise employee), client (client, customer, prospect, partner), employee \
(a colleague or staff member of the employee's own company), self, or unknown.
- is_prescription: true only for prescription medication.
- is_mobile_handset: true only for mobile phone hardware (not accessories).
- is_entertainment_venue: true for tickets or fees for golf, sporting events, theatre, concerts or \
similar venues.

## Confidence
A number from 0 to 1 that the category is right:
- 0.9-1.0: unambiguous.
- 0.7-0.89: very likely; minor ambiguity.
- 0.5-0.69: plausible, but another category is a real possibility.
- below 0.5: you cannot tell what the item is.

Keep each rationale under 15 words. Return one entry per input line, in input order."""


CLASSIFIER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "line_id",
                    "category",
                    "confidence",
                    "is_gift",
                    "recipient",
                    "recipient_type",
                    "is_prescription",
                    "is_mobile_handset",
                    "is_entertainment_venue",
                    "rationale",
                ],
                "properties": {
                    "line_id": {"type": "string"},
                    "category": {"type": "string", "enum": sorted(load_taxonomy())},
                    "confidence": {"type": "number"},
                    "is_gift": {"type": "boolean"},
                    "recipient": {"type": ["string", "null"]},
                    "recipient_type": {
                        "type": "string",
                        "enum": ["client", "employee", "government_official", "self", "unknown"],
                    },
                    "is_prescription": {"type": "boolean"},
                    "is_mobile_handset": {"type": "boolean"},
                    "is_entertainment_venue": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

"""Oracle ablation (ADR-023) — EVALUATION ONLY.

Feeds gold categories (plus a small hand annotation of item facts) to the real retriever, engine and
reporter. It measures the deterministic half of the system in isolation: if the oracle is right and
the pipeline is wrong, the error came from normalisation or classification.
"""

from __future__ import annotations

import json

from .config import FIXTURES_DIR
from .data import is_restricted, load_gold, load_receipts
from .models import ClassifiedItem, ItemAttributes, ReceiptResult

ATTRIBUTES_PATH = FIXTURES_DIR / "oracle_attributes.json"


def oracle_items() -> dict[str, list[ClassifiedItem]]:
    gold = load_gold()
    attributes = {
        k: v for k, v in json.loads(ATTRIBUTES_PATH.read_text()).items() if not k.startswith("_")
    }
    classified = {}
    for receipt in load_receipts():
        categories = gold[receipt.receipt_id].item_categories
        classified[receipt.receipt_id] = [
            ClassifiedItem(
                line_id=line.line_id,
                description_raw=line.description_raw,
                description_en=line.description_raw,
                category=categories[line.line_id],
                restricted=is_restricted(categories[line.line_id]),
                confidence=1.0,
                attributes=ItemAttributes(**attributes.get(line.line_id, {})),
                rationale="oracle: gold category",
                quantity=line.quantity,
                unit_price_usd=line.amount_usd / line.quantity if line.quantity else 0.0,
                amount_usd=line.amount_usd,
            )
            for line in receipt.line_items
        ]
    return classified


def run_oracle(threshold: float = 0.5) -> list[ReceiptResult]:
    from .pipeline import decide_all

    return decide_all(load_receipts(), oracle_items(), threshold, run="oracle")

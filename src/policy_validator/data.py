"""Loading receipts, gold labels and the category taxonomy.

`load_receipts` is the only loader the pipeline uses and it strips every label. `load_gold` exists
for evaluation and must never feed the pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .config import OUT_OF_SCOPE_RECEIPTS, RECEIPTS_PATH, TAXONOMY_PATH
from .models import Receipt

_LABEL_KEYS = {"labels", "notes"}


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_receipts(path: Path = RECEIPTS_PATH) -> list[Receipt]:
    """Pipeline input: receipts with `labels`, `notes` and line-item labels removed."""
    receipts = []
    for raw in _read_jsonl(path):
        clean = {k: v for k, v in raw.items() if k not in _LABEL_KEYS}
        clean["line_items"] = [
            {k: v for k, v in item.items() if k != "labels"} for item in raw["line_items"]
        ]
        receipts.append(Receipt.model_validate(clean))
    return receipts


@dataclass(frozen=True)
class GoldReceipt:
    receipt_id: str
    disposition: str
    exceptions: list[dict]
    review_signals: list[dict]
    item_categories: dict[str, str]
    notes: str

    @property
    def in_scope(self) -> bool:
        return self.receipt_id not in OUT_OF_SCOPE_RECEIPTS


def load_gold(path: Path = RECEIPTS_PATH) -> dict[str, GoldReceipt]:
    """Evaluation only: the correct answers keyed by receipt ID."""
    gold = {}
    for raw in _read_jsonl(path):
        labels = raw["labels"]
        gold[raw["receipt_id"]] = GoldReceipt(
            receipt_id=raw["receipt_id"],
            disposition=labels["disposition"],
            exceptions=labels["expected_exceptions"],
            review_signals=labels["review_signals"],
            item_categories={i["line_id"]: i["labels"]["category"] for i in raw["line_items"]},
            notes=raw.get("notes", ""),
        )
    return gold


@dataclass(frozen=True)
class TaxonomyEntry:
    category: str
    restricted: bool
    examples: str


@cache
def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, TaxonomyEntry]:
    """Parse the taxonomy table: | `category` | yes/no | examples |."""
    row = re.compile(r"^\|\s*`(?P<cat>[a-z_]+)`\s*\|\s*(?P<r>yes|no)\s*\|\s*(?P<ex>.*?)\s*\|\s*$")
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := row.match(line):
            entries[m["cat"]] = TaxonomyEntry(m["cat"], m["r"] == "yes", m["ex"])
    return entries


def is_restricted(category: str) -> bool:
    """`restricted` is a property of the category, not a separate prediction (ADR-015)."""
    return load_taxonomy()[category].restricted

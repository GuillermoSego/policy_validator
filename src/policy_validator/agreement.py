"""Two-model agreement as the EXC-03 confidence (ADR-043).

Self-reported confidence carried no signal on this data (ADR-037). Here the production model's
classification is kept, but an item's confidence becomes 0 when a second, independent model assigns
a different category — so disagreement, not self-assessment, decides what is "uncertain".
"""

from __future__ import annotations

from .models import ClassifiedItem, ReceiptResult


def agreement_items(
    primary: dict[str, ReceiptResult], secondary: dict[str, ReceiptResult]
) -> dict[str, list[ClassifiedItem]]:
    combined: dict[str, list[ClassifiedItem]] = {}
    for rid, result in primary.items():
        other = {i.line_id: i for i in secondary[rid].line_items}
        items = []
        for item in result.line_items:
            second = other[item.line_id]
            if second.category == item.category:
                confidence = min(item.confidence, second.confidence)
                rationale = item.rationale
            else:
                confidence = 0.0
                rationale = (
                    f"models disagree: {result.model_id} says {item.category}, "
                    f"{secondary[rid].model_id} says {second.category}"
                )
            items.append(item.model_copy(update={"confidence": confidence, "rationale": rationale}))
        combined[rid] = items
    return combined


def disagreements(
    primary: dict[str, ReceiptResult], secondary: dict[str, ReceiptResult]
) -> list[dict]:
    rows = []
    for rid, result in primary.items():
        other = {i.line_id: i for i in secondary[rid].line_items}
        for item in result.line_items:
            if other[item.line_id].category != item.category:
                rows.append(
                    {
                        "receipt_id": rid,
                        "line_id": item.line_id,
                        "text": item.description_raw,
                        "primary": item.category,
                        "secondary": other[item.line_id].category,
                    }
                )
    return rows

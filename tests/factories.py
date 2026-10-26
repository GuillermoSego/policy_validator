"""Hand-written receipt builders for engine tests — independent of receipts.jsonl and the LLM."""

from __future__ import annotations

from policy_validator.data import is_restricted
from policy_validator.engine import Decision, evaluate_batch
from policy_validator.models import ClassifiedItem, ItemAttributes, LineItem, Receipt

THRESHOLD = 0.5


def item(
    line_id: str,
    category: str,
    amount_usd: float,
    *,
    quantity: float = 1,
    confidence: float = 0.95,
    **attributes,
) -> ClassifiedItem:
    return ClassifiedItem(
        line_id=line_id,
        description_raw=f"{category} item",
        description_en=f"{category} item",
        category=category,
        restricted=is_restricted(category),
        confidence=confidence,
        attributes=ItemAttributes(**attributes),
        quantity=quantity,
        unit_price_usd=amount_usd / quantity,
        amount_usd=amount_usd,
    )


def receipt(receipt_id: str, items: list[ClassifiedItem], **fields) -> Receipt:
    total_usd = round(sum(i.amount_usd for i in items), 2)
    fx = fields.pop("fx_rate_to_usd", 1.0)
    base = dict(
        receipt_id=receipt_id,
        employee_id=f"E-{receipt_id}",
        employee_country="US",
        entity="GLOBAL",
        submitted_expense_type="Meals - Individual",
        merchant_name="Test Merchant",
        mcc="5812",
        mcc_description="Eating places and restaurants",
        transaction_datetime="2026-04-14T12:00:00",
        currency="USD",
        fx_rate_to_usd=fx,
        total_amount=round(total_usd / fx, 2) if fx else total_usd,
        total_amount_usd=total_usd,
        attendee_count=None,
        trip_id=None,
        trip_nights=None,
        pre_approval_ref=None,
        itemized=True,
        line_items=[
            LineItem(
                line_id=i.line_id,
                description_raw=i.description_raw,
                language="en",
                quantity=i.quantity,
                unit_price=i.unit_price_usd / fx if fx else i.unit_price_usd,
                amount=i.amount_usd / fx if fx else i.amount_usd,
                amount_usd=i.amount_usd,
            )
            for i in items
        ],
    )
    base.update(fields)
    return Receipt.model_validate(base)


def decide(*pairs: tuple[Receipt, list[ClassifiedItem]]) -> dict[str, Decision]:
    receipts = [r for r, _ in pairs]
    classified = {r.receipt_id: items for r, items in pairs}
    return evaluate_batch(receipts, classified, THRESHOLD)


def decide_one(r: Receipt, items: list[ClassifiedItem]) -> Decision:
    return decide((r, items))[r.receipt_id]


def rule_ids(decision: Decision) -> set[str]:
    return {e.rule_id for e in decision.exceptions}


def signal_ids(decision: Decision) -> set[str]:
    return {s.rule_id for s in decision.signals}


def lines_of(decision: Decision, rule_id: str) -> tuple[str, ...]:
    return next(e.line_ids for e in decision.exceptions if e.rule_id == rule_id)

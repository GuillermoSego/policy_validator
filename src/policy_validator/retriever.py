"""3. Policy retriever — selects the rules that could apply to a receipt (ADR-005, ADR-019).

Retrieval is deterministic and recall-oriented: it looks at the receipt's facets (item categories
and attributes, MCC, declared expense type, entity, currency, itemization) and returns every rule
that *could* apply, with the reason it was retrieved. Over-retrieval is cheap — the engine decides
whether a rule actually fires — but a rule that is not retrieved is never evaluated.
"""

from __future__ import annotations

from collections import OrderedDict

from .models import ClassifiedItem, Receipt, RetrievedRule
from .policy_registry import load_registry

# Rules every receipt is checked against (documentation and merchant risk).
ALWAYS = ("DOC-01", "DOC-02", "DOC-03", "MCC-01", "MCC-02")

CATEGORY_RULES = {
    "alcohol": ("ALC-01", "ALC-02", "ALC-03"),
    "tobacco": ("PERS-03",),
    "personal_electronics": ("TECH-01", "TECH-03"),
    "gift": ("GIFT-01", "GIFT-03", "GIFT-04"),
    "gift_card": ("GIFT-02",),
    "jewelry": ("GIFT-01", "GIFT-03", "GIFT-04"),
    "household_goods": ("HOUSE-01",),
    "personal_care": ("PERS-01",),
    "clothing": ("PERS-02",),
    "gambling": ("ENT-02",),
    "computer_accessory": ("TECH-02",),
    "health_otc": ("HEALTH-01",),
    "laundry_service": ("LAUNDRY-01",),
    "software_subscription": ("TECH-04",),
    "food_beverage": ("MEAL-01", "MEAL-02"),
    "other": ("ENT-01",),
}

ATTRIBUTE_RULES = {
    "is_gift": ("GIFT-01", "GIFT-03", "GIFT-04"),
    "is_prescription": ("HEALTH-01",),
    "is_mobile_handset": ("TECH-03",),
    "is_entertainment_venue": ("ENT-01",),
}

EXPENSE_TYPE_RULES = {
    "Meals - Individual": ("MEAL-01", "MEAL-02"),
    "Meals - Team": ("MEAL-01", "MEAL-02"),
    "Client Entertainment": ("MEAL-01", "MEAL-02", "ALC-01", "ENT-01", "GIFT-04"),
    "Client Gifts": ("GIFT-01", "GIFT-02", "GIFT-03", "GIFT-04"),
    "Software": ("TECH-04",),
    "Computer Equipment": ("TECH-01", "TECH-02", "TECH-03", "TECH-04"),
}

MCC_RULES = {
    "5921": ("ALC-03",),
    "5813": ("ALC-01", "ALC-02"),
    "7995": ("ENT-02",),
    "5993": ("PERS-03",),
    "7297": ("PERS-01",),
    "5944": ("GIFT-01",),
    "5912": ("HEALTH-01",),
}

# Regional rules that override a global rule for an entity (regional-addendum.md).
REGIONAL_OVERRIDES = {
    "APAC": {"ALC-01": "REG-01", "ALC-02": "REG-01", "ALC-03": "REG-01", "MEAL-01": "REG-02"},
    "EMEA": {"MEAL-01": "REG-03"},
}
ENTITY_RULES = {"EMEA": ("REG-04",)}


def retrieve(receipt: Receipt, items: list[ClassifiedItem]) -> list[RetrievedRule]:
    registry = load_registry()
    found: OrderedDict[str, str] = OrderedDict()

    def add(rule_ids: tuple[str, ...], reason: str) -> None:
        for rule_id in rule_ids:
            found.setdefault(rule_id, reason)

    add(ALWAYS, "applies to every receipt")
    for item in items:
        add(CATEGORY_RULES.get(item.category, ()), f"{item.line_id} is {item.category}")
        attrs = item.attributes
        for attribute, rules in ATTRIBUTE_RULES.items():
            if getattr(attrs, attribute):
                add(rules, f"{item.line_id} has {attribute}")
        if attrs.recipient_type == "government_official":
            add(("GIFT-04",), f"{item.line_id} is provided to a government official")
        elif attrs.recipient:
            add(("GIFT-01", "GIFT-03"), f"{item.line_id} names a recipient")

    declared = receipt.submitted_expense_type
    add(EXPENSE_TYPE_RULES.get(declared, ()), f"declared as {declared}")
    add(MCC_RULES.get(receipt.mcc, ()), f"MCC {receipt.mcc}")
    if receipt.currency != "USD":
        add(("DOC-04",), f"currency {receipt.currency}")
    add(ENTITY_RULES.get(receipt.entity, ()), f"{receipt.entity} entity")

    for global_rule, regional_rule in REGIONAL_OVERRIDES.get(receipt.entity, {}).items():
        if global_rule in found:
            add((regional_rule,), f"{receipt.entity} override of {global_rule}")

    return [
        RetrievedRule(rule_id=rule_id, policy_doc=registry[rule_id].policy_doc, reason=reason)
        for rule_id, reason in found.items()
    ]


def retrieved_ids(rules: list[RetrievedRule]) -> set[str]:
    return {r.rule_id for r in rules}

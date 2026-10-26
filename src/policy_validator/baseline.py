"""Keyword baseline — the kind of system this project replaces (ADR-022).

A legacy-style matcher: English keyword lists per category, restricted categories checked first
(any restricted word wins, which is how keyword flagging systems behave), and a default category
from the declared expense type when nothing matches. Its output feeds the *same* retriever and
engine as the pipeline, so every metric compares like with like and isolates the classifier.

`legacy_disposition` is the bare legacy behaviour: flag a receipt whenever a restricted keyword
appears, with no rule engine at all.
"""

from __future__ import annotations

import re

from .data import is_restricted
from .models import ClassifiedItem, ItemAttributes, Receipt

# Order matters: restricted categories first, then ordinary spend.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "gift_card": ("gift card", "giftcard", "voucher", "prepaid card"),
    "alcohol": (
        "beer",
        "wine",
        "ale",
        "ipa",
        "lager",
        "stout",
        "rum",
        "vodka",
        "whisky",
        "whiskey",
        "gin",
        "tequila",
        "bourbon",
        "brandy",
        "cognac",
        "champagne",
        "prosecco",
        "cocktail",
        "mojito",
        "margarita",
        "sake",
        "liquor",
    ),
    "tobacco": ("cigarette", "cigar", "tobacco", "vape", "e-liquid", "marlboro"),
    "personal_electronics": (
        "headphones",
        "earbuds",
        "airpods",
        "ipad",
        "tablet",
        "smart watch",
        "smartwatch",
        "camera",
        "drone",
        "speaker",
        "kindle",
        "fitbit",
    ),
    "gambling": ("casino", "poker", "lottery", "betting", "chips"),
    "jewelry": ("bracelet", "necklace", "earrings", "jewelry", "jewellery"),
    "gift": ("gift", "flowers", "bouquet", "greeting card"),
    "household_goods": (
        "detergent",
        "paper towels",
        "dish soap",
        "cleaning",
        "toilet paper",
        "tissues",
        "kitchen",
        "mug",
        "glassware",
        "bedding",
    ),
    "personal_care": (
        "massage",
        "spa",
        "salon",
        "haircut",
        "shampoo",
        "toothpaste",
        "razor",
        "cosmetic",
        "toiletries",
    ),
    "clothing": ("shirt", "socks", "shoes", "jacket", "tie", "belt", "dress", "trousers", "pants"),
    "service_fee": ("gratuity", "tip", "service charge", "delivery fee", "booking fee"),
    "computer_accessory": (
        "usb",
        "hdmi",
        "cable",
        "adapter",
        "dock",
        "docking",
        "monitor",
        "mouse",
        "keyboard",
        "webcam",
    ),
    "office_supplies": ("pen", "pens", "paper", "legal pad", "legal pads", "notebook", "stapler"),
    "lodging": ("room", "occupancy", "resort fee", "lodging"),
    "ground_transport": ("parking", "taxi", "uber", "lyft", "toll", "fuel", "train"),
    "airfare": ("airfare", "flight", "baggage fee", "seat fee"),
    "laundry_service": ("dry cleaning", "laundry", "pressing"),
    "health_otc": ("ibuprofen", "aspirin", "lozenges", "tylenol", "antacid", "bandage"),
    "software_subscription": ("subscription", "license", "licence", "saas", "annual seat"),
}

DEFAULT_BY_EXPENSE_TYPE = {
    "Meals - Individual": "food_beverage",
    "Meals - Team": "food_beverage",
    "Client Entertainment": "food_beverage",
    "Client Gifts": "gift",
    "Lodging": "lodging",
    "Travel - Other": "other",
    "Office Supplies": "office_supplies",
    "Computer Equipment": "computer_accessory",
    "Software": "software_subscription",
}

GOVERNMENT_WORDS = ("official", "government", "ministry", "city", "municipal", "procurement")
_RECIPIENT = re.compile(r"\bfor ([A-Z][\w.]*(?: [A-Z][\w.]*)*)")
_PATTERNS = {
    category: re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)
    for category, words in KEYWORDS.items()
}


def keyword_category(text: str, declared_type: str) -> str:
    for category, pattern in _PATTERNS.items():
        if pattern.search(text):
            return category
    return DEFAULT_BY_EXPENSE_TYPE.get(declared_type, "other")


def classify_receipt(receipt: Receipt) -> list[ClassifiedItem]:
    items = []
    for line in receipt.line_items:
        text = line.description_raw
        category = (
            keyword_category(text, receipt.submitted_expense_type) if receipt.itemized else "other"
        )
        recipient = m.group(1) if (m := _RECIPIENT.search(text)) else None
        government = any(w in text.lower() for w in GOVERNMENT_WORDS)
        attributes = ItemAttributes(
            is_gift=category in ("gift", "jewelry") or "gift" in text.lower(),
            recipient=recipient,
            recipient_type="government_official"
            if government
            else ("client" if recipient else "unknown"),
        )
        items.append(
            ClassifiedItem(
                line_id=line.line_id,
                description_raw=text,
                description_en=text,
                category=category,
                restricted=is_restricted(category),
                confidence=1.0,
                attributes=attributes,
                rationale="keyword baseline",
                quantity=line.quantity,
                unit_price_usd=line.amount_usd / line.quantity
                if line.quantity
                else line.amount_usd,
                amount_usd=line.amount_usd,
            )
        )
    return items


def legacy_disposition(items: list[ClassifiedItem]) -> str:
    """The bare legacy system: any restricted keyword flags the receipt."""
    return "flag" if any(i.restricted for i in items) else "pass"

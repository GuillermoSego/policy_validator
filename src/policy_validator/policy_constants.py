"""Severities, thresholds and lookup tables taken from the policy text (ADR-006, ADR-029).

Every value here is checked against the policy markdown by `tests/test_policy_registry.py`: if a
policy document changes a number, the build breaks instead of the engine silently diverging.
"""

from __future__ import annotations

from typing import Literal

Scope = Literal["receipt", "line"]

# rule_id -> severity. HEALTH-01 has two (OTC low, prescription medium) and is handled in code.
SEVERITY = {
    "ALC-01": "high",
    "ALC-02": "medium",
    "ALC-03": "high",
    "DOC-01": "medium",
    "DOC-02": "medium",
    "DOC-03": "medium",
    "DOC-04": "medium",
    "ENT-01": "medium",
    "ENT-02": "high",
    "GIFT-01": "medium",
    "GIFT-02": "high",
    "GIFT-03": "medium",
    "GIFT-04": "critical",
    "HEALTH-01": "low",
    "HOUSE-01": "medium",
    "LAUNDRY-01": "low",
    "MCC-01": "high",
    "MEAL-01": "medium",
    "MEAL-02": "low",
    "PERS-01": "medium",
    "PERS-02": "medium",
    "PERS-03": "high",
    "REG-01": "high",
    "REG-02": "medium",
    "REG-03": "medium",
    "REG-04": "low",
    "TECH-01": "high",
    "TECH-02": "medium",
    "TECH-03": "high",
    "TECH-04": "low",
}
HEALTH_01_PRESCRIPTION_SEVERITY = "medium"

# EXC-04: rules about the receipt as a whole cite no line items.
WHOLE_RECEIPT_RULES = frozenset(
    {
        "MCC-01",
        "MEAL-01",
        "MEAL-02",
        "DOC-01",
        "DOC-02",
        "DOC-03",
        "DOC-04",
        "REG-02",
        "REG-03",
        "REG-04",
        "TIME-03",
    }
)

# EXC-01 severity order.
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# --- Thresholds (USD unless stated) -------------------------------------------------------------
MEAL_CAP_DOMESTIC_USD = 75.0  # MEAL-01
MEAL_CAP_INTERNATIONAL_USD = 100.0  # MEAL-01
MEAL_ATTENDEE_DOC_THRESHOLD_USD = 150.0  # MEAL-02
APAC_MEAL_CAP_USD = 60.0  # REG-02
EMEA_MEAL_CAP_EUR = 70.0  # REG-03
EMEA_VAT_THRESHOLD_EUR = 50.0  # REG-04
ALCOHOL_CAP_PER_ATTENDEE_USD = 30.0  # ALC-02
ALCOHOL_MIN_ATTENDEES = 2  # ALC-01
PERIPHERAL_UNIT_CAP_USD = 200.0  # TECH-02
GIFT_CAP_PER_RECIPIENT_USD = 50.0  # GIFT-01
GIFT_NAMED_RECIPIENT_MIN_USD = 10.0  # GIFT-01
OTC_TRIP_CAP_USD = 25.0  # HEALTH-01
BAGGAGE_DELAY_ALLOWANCE_USD = 150.0  # PERS-01 / PERS-02
LAUNDRY_MIN_TRIP_NIGHTS = 4  # LAUNDRY-01
ITEMIZATION_THRESHOLD_USD = 75.0  # DOC-01

# --- Lookup tables -------------------------------------------------------------------------------
MEAL_EXPENSE_TYPES = frozenset({"Meals - Individual", "Meals - Team", "Client Entertainment"})
MEAL_SPEND_CATEGORIES = frozenset({"food_beverage", "alcohol", "service_fee"})  # MEAL-01

# ALC-01/ALC-02 scope: alcohol served on the premises (ALC scope note, MCC-03).
ON_PREMISE_ALCOHOL_MCCS = frozenset({"5812", "5813", "7011"})

# merchant-category-risk.md; any MCC not listed is low risk.
HIGH_RISK_MCCS = frozenset({"5921", "5993", "7995", "7297", "5944"})
MEDIUM_RISK_MCCS = frozenset({"5813", "5912", "5311", "5411", "5732"})

# DOC-03: declared expense type -> categories it covers.
EXPENSE_TYPE_COVERS = {
    "Meals - Individual": frozenset({"food_beverage", "alcohol"}),
    "Meals - Team": frozenset({"food_beverage", "alcohol"}),
    "Client Entertainment": frozenset({"food_beverage", "alcohol"}),
    "Client Gifts": frozenset({"gift", "gift_card", "jewelry"}),
    "Lodging": frozenset({"lodging", "ground_transport", "laundry_service"}),
    "Travel - Other": frozenset(
        {"laundry_service", "health_otc", "ground_transport", "clothing", "personal_care"}
    ),
    "Office Supplies": frozenset({"office_supplies", "computer_accessory"}),
    "Computer Equipment": frozenset(
        {"computer_accessory", "personal_electronics", "software_subscription"}
    ),
    "Software": frozenset({"software_subscription"}),
}
DOC_03_IGNORED_CATEGORIES = frozenset({"service_fee", "other"})

# Categories that are never gifts under GIFT-01 (meal lines; gift cards fall under GIFT-02 alone).
NOT_GIFT_01_CATEGORIES = frozenset({"food_beverage", "alcohol", "service_fee", "gift_card"})

# Approval type each rule requires (EXC-02).
REQUIRED_APPROVAL = {
    "TECH-02": "pre_approval",
    "ENT-01": "vp_approval",
    "TECH-04": "manager_approval",
    "PERS-01": "baggage_delay",
    "PERS-02": "baggage_delay",
}

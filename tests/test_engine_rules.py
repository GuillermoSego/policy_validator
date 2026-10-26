"""Boundary and precedence tests per rule family."""

import pytest

from policy_validator.engine import RuleHit, disposition

from .factories import decide, decide_one, item, lines_of, receipt, rule_ids, signal_ids

# --- Disposition (EXC-01) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "severities,signals,expected",
    [
        ([], [], "pass"),
        ([], ["MCC-02"], "review"),
        (["low"], [], "review"),
        (["low", "low"], ["MCC-02"], "review"),
        (["medium"], [], "flag"),
        (["low", "high"], [], "flag"),
        (["critical"], [], "flag"),
    ],
)
def test_exc_01_ladder(severities, signals, expected):
    exceptions = [RuleHit(f"R-{n}", "exception", "", (), s) for n, s in enumerate(severities)]
    sigs = [RuleHit(s, "signal", "") for s in signals]
    assert disposition(exceptions, sigs) == expected


# --- Alcohol ---------------------------------------------------------------------------------


def test_alcohol_on_individual_meal_is_alc_01():
    items = [
        item("L1", "food_beverage", 38.0),
        item("L2", "alcohol", 18.0),
        item("L3", "service_fee", 8.4),
    ]
    d = decide_one(receipt("R", items), items)
    assert rule_ids(d) == {"ALC-01"}
    assert lines_of(d, "ALC-01") == ("L2",)


def test_permitted_alcohol_over_cap_is_alc_02_not_alc_01():
    items = [
        item("L1", "food_beverage", 248.0),
        item("L2", "alcohol", 110.0),
        item("L3", "service_fee", 71.6),
    ]
    r = receipt("R", items, submitted_expense_type="Client Entertainment", attendee_count=2)
    d = decide_one(r, items)
    assert rule_ids(d) == {"ALC-02", "MEAL-01"}


def test_alcohol_cap_boundary_is_inclusive():
    items = [item("L1", "alcohol", 60.0)]
    r = receipt("R", items, submitted_expense_type="Client Entertainment", attendee_count=2)
    assert "ALC-02" not in rule_ids(decide_one(r, items))


def test_retail_alcohol_is_alc_03_plus_mcc_01_whatever_the_context():
    items = [item("L1", "alcohol", 72.0), item("L2", "food_beverage", 7.0)]
    r = receipt(
        "R",
        items,
        submitted_expense_type="Client Entertainment",
        attendee_count=6,
        mcc="5921",
        mcc_description="Package stores",
        pre_approval_ref="PA-2026-1",
    )
    assert rule_ids(decide_one(r, items)) == {"ALC-03", "MCC-01"}


def test_supermarket_cooking_wine_is_retail_alcohol():
    items = [item("L1", "household_goods", 19.99), item("L2", "alcohol", 8.99)]
    r = receipt(
        "R",
        items,
        submitted_expense_type="Office Supplies",
        mcc="5411",
        mcc_description="Grocery stores",
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"ALC-03", "HOUSE-01", "DOC-03"}
    assert signal_ids(d) == {"MCC-02"}


def test_bar_is_on_premise_not_retail():
    items = [item("L1", "alcohol", 20.0)]
    r = receipt("R", items, mcc="5813", mcc_description="Bars")
    d = decide_one(r, items)
    assert rule_ids(d) == {"ALC-01"}
    assert signal_ids(d) == {"MCC-02"}


# --- Meals -----------------------------------------------------------------------------------


def test_meal_cap_counts_food_drink_and_gratuity_only():
    items = [item("L1", "food_beverage", 70.0), item("L2", "gift", 9.0)]
    assert "MEAL-01" not in rule_ids(decide_one(receipt("R", items), items))


def test_meal_cap_is_per_person_per_day_across_receipts():
    a = [item("A1", "food_beverage", 40.0)]
    b = [item("B1", "food_beverage", 40.0)]
    ra = receipt("A", a, employee_id="E1")
    rb = receipt("B", b, employee_id="E1", transaction_datetime="2026-04-14T19:00:00")
    decisions = decide((ra, a), (rb, b))
    assert "MEAL-01" in rule_ids(decisions["A"])
    assert "MEAL-01" in rule_ids(decisions["B"])


def test_meal_cap_boundary_and_attendee_division():
    items = [item("L1", "food_beverage", 150.0)]
    r = receipt("R", items, submitted_expense_type="Meals - Team", attendee_count=2)
    assert decide_one(r, items).disposition == "pass"


def test_international_cap_is_higher():
    items = [item("L1", "food_beverage", 90.0)]
    r = receipt("R", items, currency="EUR", fx_rate_to_usd=1.08)
    assert "MEAL-01" not in rule_ids(decide_one(r, items))


def test_apac_and_emea_caps_replace_meal_01():
    apac = [item("L1", "food_beverage", 65.0)]
    r = receipt(
        "R", apac, employee_country="JP", entity="APAC", currency="JPY", fx_rate_to_usd=0.0067
    )
    assert rule_ids(decide_one(r, apac)) == {"REG-02"}

    emea = [item("L1", "food_beverage", 80.0)]  # EUR 74.07 > EUR 70
    r = receipt(
        "R", emea, employee_country="DE", entity="EMEA", currency="EUR", fx_rate_to_usd=1.08
    )
    assert "REG-03" in rule_ids(decide_one(r, emea))


def test_emea_meal_without_eur_rate_is_a_review_signal():
    items = [item("L1", "food_beverage", 30.0)]
    r = receipt("R", items, employee_country="GB", entity="EMEA", currency="USD")
    d = decide_one(r, items)
    assert {"REG-03", "REG-04"} <= signal_ids(d)
    assert d.exceptions == ()


def test_meal_02_needs_attendee_count_above_150():
    items = [item("L1", "food_beverage", 160.0)]
    r = receipt("R", items, submitted_expense_type="Meals - Team")
    assert "MEAL-02" in rule_ids(decide_one(r, items))
    r = receipt("R", items, submitted_expense_type="Meals - Team", attendee_count=4)
    assert "MEAL-02" not in rule_ids(decide_one(r, items))


def test_non_itemized_receipt_uses_full_total():
    items = [item("L1", "other", 186.0)]
    r = receipt("R", items, submitted_expense_type="Meals - Team", attendee_count=3, itemized=False)
    d = decide_one(r, items)
    assert rule_ids(d) == {"DOC-01"}
    assert lines_of(d, "DOC-01") == ()


# --- Gifts -----------------------------------------------------------------------------------


def test_named_client_gift_over_cap():
    items = [
        item("L1", "jewelry", 180.0, is_gift=True, recipient="A. Moreau", recipient_type="client")
    ]
    r = receipt(
        "R",
        items,
        submitted_expense_type="Client Gifts",
        mcc="5944",
        mcc_description="Jewelry stores",
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"GIFT-01", "MCC-01"}


def test_gift_card_is_gift_02_alone_and_small_card_is_fine():
    items = [item("L1", "gift_card", 100.0), item("L2", "gift", 4.99)]
    r = receipt(
        "R",
        items,
        submitted_expense_type="Client Gifts",
        mcc="5311",
        mcc_description="Department stores",
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"GIFT-02"}


def test_unnamed_gift_of_ten_dollars_needs_recipient():
    items = [item("L1", "gift", 10.0)]
    r = receipt("R", items, submitted_expense_type="Client Gifts")
    assert lines_of(decide_one(r, items), "GIFT-01") == ("L1",)


def test_government_official_is_critical_and_replaces_gift_01():
    items = [
        item(
            "L1",
            "food_beverage",
            68.0,
            quantity=2,
            recipient="R. Delgado",
            recipient_type="government_official",
        ),
        item(
            "L2",
            "gift",
            45.0,
            is_gift=True,
            recipient="R. Delgado",
            recipient_type="government_official",
        ),
        item("L3", "service_fee", 10.0, recipient_type="government_official"),
    ]
    r = receipt("R", items, submitted_expense_type="Client Entertainment", attendee_count=2)
    d = decide_one(r, items)
    assert rule_ids(d) == {"GIFT-04"}
    assert lines_of(d, "GIFT-04") == ("L1", "L2")
    assert d.exceptions[0].severity == "critical"


def test_employee_gift_is_gift_03():
    items = [item("L1", "gift", 30.0, is_gift=True, recipient="Jane", recipient_type="employee")]
    r = receipt("R", items, submitted_expense_type="Client Gifts")
    assert rule_ids(decide_one(r, items)) == {"GIFT-03"}


# --- Technology ------------------------------------------------------------------------------


def test_personal_electronics_and_case():
    items = [item("L1", "personal_electronics", 601.66), item("L2", "personal_electronics", 48.91)]
    r = receipt(
        "R",
        items,
        submitted_expense_type="Computer Equipment",
        mcc="5732",
        mcc_description="Electronics stores",
    )
    d = decide_one(r, items)
    assert lines_of(d, "TECH-01") == ("L1", "L2")
    assert "DOC-03" not in rule_ids(d)


def test_pre_approval_waives_tech_02():
    items = [item("L1", "computer_accessory", 329.0)]
    r = receipt(
        "R", items, submitted_expense_type="Computer Equipment", pre_approval_ref="PA-2026-0001"
    )
    assert decide_one(r, items).disposition == "pass"


def test_unit_price_not_line_total_drives_tech_02():
    items = [item("L1", "computer_accessory", 300.0, quantity=2)]  # $150 each
    r = receipt("R", items, submitted_expense_type="Computer Equipment")
    assert "TECH-02" not in rule_ids(decide_one(r, items))


def test_mobile_handset_is_tech_03_not_tech_01():
    items = [item("L1", "personal_electronics", 799.0, is_mobile_handset=True)]
    r = receipt("R", items, submitted_expense_type="Computer Equipment")
    assert rule_ids(decide_one(r, items)) == {"TECH-03"}


def test_software_needs_manager_approval_and_pa_does_not_count():
    items = [item("L1", "software_subscription", 144.0)]
    r = receipt("R", items, submitted_expense_type="Software", pre_approval_ref="PA-2026-1")
    d = decide_one(r, items)
    assert rule_ids(d) == {"TECH-04"}
    assert d.disposition == "review"


# --- Non-reimbursable, health, laundry --------------------------------------------------------


def test_otc_cap_is_per_trip_across_receipts():
    a = [item("A1", "health_otc", 15.0)]
    b = [item("B1", "health_otc", 15.0)]
    kw = dict(submitted_expense_type="Travel - Other", trip_id="T9", trip_nights=3)
    decisions = decide((receipt("A", a, **kw), a), (receipt("B", b, **kw), b))
    assert lines_of(decisions["A"], "HEALTH-01") == ("A1",)
    assert lines_of(decisions["B"], "HEALTH-01") == ("B1",)


def test_otc_without_trip_is_low_and_prescription_is_medium():
    otc = [item("L1", "health_otc", 5.0)]
    r = receipt("R", otc, submitted_expense_type="Travel - Other")
    d = decide_one(r, otc)
    assert d.exceptions[0].severity == "low"

    rx = [item("L1", "health_otc", 5.0, is_prescription=True)]
    r = receipt("R", rx, submitted_expense_type="Travel - Other", trip_id="T1", trip_nights=2)
    assert decide_one(r, rx).exceptions[0].severity == "medium"


def test_laundry_boundary_four_nights():
    items = [item("L1", "laundry_service", 34.0)]
    r = receipt("R", items, submitted_expense_type="Travel - Other", trip_id="T", trip_nights=4)
    assert decide_one(r, items).disposition == "pass"


def test_spa_at_massage_parlor_is_three_separate_exceptions():
    items = [item("L1", "personal_care", 120.0), item("L2", "service_fee", 20.0)]
    r = receipt(
        "R", items, submitted_expense_type="Lodging", mcc="7297", mcc_description="Massage parlors"
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"MCC-01", "PERS-01", "DOC-03"}
    assert lines_of(d, "PERS-01") == ("L1",)


def test_tobacco_on_small_receipt():
    items = [item("L1", "tobacco", 11.5), item("L2", "food_beverage", 9.0)]
    assert rule_ids(decide_one(receipt("R", items), items)) == {"PERS-03"}


# --- Documentation and uncertainty -----------------------------------------------------------


def test_doc_03_ignores_service_fees_and_other():
    items = [item("L1", "service_fee", 10.0), item("L2", "other", 10.0)]
    r = receipt("R", items, submitted_expense_type="Software")
    assert "DOC-03" not in rule_ids(decide_one(r, items))


def test_doc_04_foreign_currency_without_rate():
    items = [item("L1", "food_beverage", 20.0)]
    r = receipt("R", items, currency="EUR", fx_rate_to_usd=None)
    assert "DOC-04" in rule_ids(decide_one(r, items))


def test_reg_04_vat_above_eur_50():
    items = [item("L1", "lodging", 64.8)]  # EUR 60
    r = receipt(
        "R",
        items,
        employee_country="FR",
        entity="EMEA",
        submitted_expense_type="Lodging",
        mcc="7011",
        mcc_description="Hotels",
        currency="EUR",
        fx_rate_to_usd=1.08,
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"REG-04"}
    assert d.disposition == "review"


def test_uncertain_item_is_exc_03_and_excluded_from_other_rules():
    items = [item("L1", "alcohol", 18.0, confidence=0.3), item("L2", "food_beverage", 20.0)]
    d = decide_one(receipt("R", items), items)
    assert d.exceptions == ()
    assert signal_ids(d) == {"EXC-03"}
    assert d.signals[0].line_ids == ("L1",)
    assert d.disposition == "review"

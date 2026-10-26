"""The five behaviours the brief asks the policy engine to get right (section 4)."""

from .factories import decide_one, item, lines_of, receipt, rule_ids, signal_ids


def test_carve_out_without_evidence_rcp_027():
    """Clothing with no baggage-delay reference is still an exception."""
    items = [item("L1", "clothing", 68.0), item("L2", "clothing", 18.0)]
    r = receipt(
        "CLOTHES",
        items,
        submitted_expense_type="Travel - Other",
        mcc="5311",
        mcc_description="Department stores",
        trip_id="T1",
        trip_nights=3,
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"PERS-02"}
    assert lines_of(d, "PERS-02") == ("L1", "L2")
    assert signal_ids(d) == {"MCC-02"}
    assert d.disposition == "flag"


def test_pre_approval_is_not_a_baggage_delay_reference():
    """EXC-02: a reference satisfies only the rule whose kind it is."""
    items = [item("L1", "clothing", 68.0)]
    r = receipt(
        "CLOTHES-PA",
        items,
        submitted_expense_type="Travel - Other",
        pre_approval_ref="PA-2026-0001",
    )
    assert "PERS-02" in rule_ids(decide_one(r, items))


def test_regional_override_rcp_016():
    """APAC alcohol is REG-01 even where the global rules would allow it."""
    items = [
        item("L1", "food_beverage", 43.2, quantity=3),
        item("L2", "alcohol", 16.2, quantity=3),
        item("L3", "service_fee", 5.94),
    ]
    r = receipt(
        "APAC-ALC",
        items,
        employee_country="IN",
        entity="APAC",
        submitted_expense_type="Client Entertainment",
        currency="INR",
        fx_rate_to_usd=0.012,
        attendee_count=3,
        pre_approval_ref="PA-2026-0398",
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"REG-01"}
    assert lines_of(d, "REG-01") == ("L2",)
    assert d.disposition == "flag"


def test_same_receipt_passes_under_global_rules():
    items = [item("L1", "food_beverage", 43.2), item("L2", "alcohol", 16.2)]
    r = receipt(
        "GLOBAL-ALC", items, submitted_expense_type="Client Entertainment", attendee_count=3
    )
    assert decide_one(r, items).disposition == "pass"


def test_threshold_boundary_rcp_006_and_rcp_026():
    """A $189 dock passes; a $329 monitor without pre-approval does not."""
    dock = [item("L1", "computer_accessory", 189.0)]
    r_dock = receipt(
        "DOCK",
        dock,
        submitted_expense_type="Computer Equipment",
        mcc="5943",
        mcc_description="Office and stationery supply",
    )
    assert decide_one(r_dock, dock).disposition == "pass"

    monitor = [item("L1", "computer_accessory", 329.0), item("L2", "computer_accessory", 14.99)]
    r_mon = receipt(
        "MONITOR",
        monitor,
        submitted_expense_type="Computer Equipment",
        mcc="5943",
        mcc_description="Office and stationery supply",
    )
    d = decide_one(r_mon, monitor)
    assert rule_ids(d) == {"TECH-02"}
    assert lines_of(d, "TECH-02") == ("L1",)
    assert d.disposition == "flag"


def test_severity_ladder_rcp_031():
    """A single low-severity exception gives review, not flag."""
    items = [item("L1", "laundry_service", 21.6)]
    r = receipt(
        "LAUNDRY",
        items,
        employee_country="PT",
        entity="EMEA",
        submitted_expense_type="Travel - Other",
        mcc="7216",
        mcc_description="Dry cleaners",
        currency="EUR",
        fx_rate_to_usd=1.08,
        trip_id="T1",
        trip_nights=2,
    )
    d = decide_one(r, items)
    assert rule_ids(d) == {"LAUNDRY-01"}
    assert d.disposition == "review"


def test_review_signal_on_its_own_rcp_028():
    """A medium-risk MCC with compliant items gives review with no exceptions."""
    items = [item("L1", "health_otc", 8.99), item("L2", "health_otc", 5.49)]
    r = receipt(
        "PHARMACY",
        items,
        submitted_expense_type="Travel - Other",
        mcc="5912",
        mcc_description="Drug stores and pharmacies",
        trip_id="T1",
        trip_nights=4,
    )
    d = decide_one(r, items)
    assert d.exceptions == ()
    assert signal_ids(d) == {"MCC-02"}
    assert d.disposition == "review"

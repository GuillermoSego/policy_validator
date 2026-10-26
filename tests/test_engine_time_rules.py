"""Transaction-pattern rules TIME-01..TIME-03 (stretch goal)."""

from .factories import decide, decide_one, item, receipt, rule_ids, signal_ids

TRIP = dict(trip_id="T1", trip_nights=3)


def test_time_01_overnight_window_is_half_open():
    items = [item("L1", "food_beverage", 20.0)]
    for clock, expected in [("00:00", True), ("02:14", True), ("04:59", True), ("05:00", False)]:
        r = receipt("R", items, transaction_datetime=f"2026-05-07T{clock}:00", **TRIP)
        d = decide_one(r, items)
        assert ("TIME-01" in signal_ids(d)) is expected, clock
        assert d.disposition == ("review" if expected else "pass")


def test_time_02_individual_travel_without_trip():
    items = [item("L1", "food_beverage", 28.0)]
    d = decide_one(receipt("R", items), items)
    assert signal_ids(d) == {"TIME-02"}
    assert d.disposition == "review"


def test_time_02_does_not_cover_team_meals_or_client_entertainment():
    items = [item("L1", "food_beverage", 28.0)]
    for declared in ("Meals - Team", "Client Entertainment", "Office Supplies"):
        r = receipt("R", items, submitted_expense_type=declared, attendee_count=2)
        assert "TIME-02" not in signal_ids(decide_one(r, items)), declared


def _meal(rid, amount, **fields):
    items = [item(f"{rid}-L1", "food_beverage", amount)]
    base = dict(employee_id="E1", merchant_name="Copper Skillet", **TRIP)
    base.update(fields)
    return receipt(rid, items, **base), items


def test_time_03_meal_split_replaces_meal_01_on_every_receipt():
    a = _meal("A", 74.0, transaction_datetime="2026-04-27T12:10:00")
    b = _meal("B", 71.5, transaction_datetime="2026-04-27T19:40:00")
    decisions = decide(a, b)
    for rid in ("A", "B"):
        assert rule_ids(decisions[rid]) == {"TIME-03"}
        assert decisions[rid].exceptions[0].severity == "high"
        assert decisions[rid].exceptions[0].line_ids == ()


def test_no_split_when_one_receipt_already_breaches_the_cap():
    a = _meal("A", 80.0)
    b = _meal("B", 10.0)
    decisions = decide(a, b)
    assert rule_ids(decisions["A"]) == {"MEAL-01"}
    assert "TIME-03" not in rule_ids(decisions["B"])


def test_no_split_across_merchants_or_days():
    a = _meal("A", 60.0)
    b = _meal("B", 60.0, merchant_name="Elsewhere")
    c = _meal("C", 60.0, transaction_datetime="2026-04-15T12:00:00")
    decisions = decide(a, b, c)
    assert all("TIME-03" not in rule_ids(d) for d in decisions.values())


def test_merchant_name_match_ignores_case_and_spacing():
    a = _meal("A", 60.0)
    b = _meal("B", 60.0, merchant_name="copper  SKILLET")
    assert "TIME-03" in rule_ids(decide(a, b)["B"])


def test_itemization_split_replaces_doc_01():
    kw = dict(employee_id="E1", itemized=False, submitted_expense_type="Office Supplies")
    a_items, b_items = [item("A1", "other", 60.0)], [item("B1", "other", 50.0)]
    decisions = decide(
        (receipt("A", a_items, **kw), a_items), (receipt("B", b_items, **kw), b_items)
    )
    for rid in ("A", "B"):
        assert rule_ids(decisions[rid]) == {"TIME-03"}


def test_gift_split_for_one_recipient_replaces_gift_01():
    kw = dict(employee_id="E1", submitted_expense_type="Client Gifts")
    gift = dict(is_gift=True, recipient="A. Client", recipient_type="client")
    a_items = [item("A1", "gift", 40.0, **gift)]
    b_items = [item("B1", "gift", 40.0, **gift)]
    decisions = decide(
        (receipt("A", a_items, **kw), a_items), (receipt("B", b_items, **kw), b_items)
    )
    for rid in ("A", "B"):
        assert rule_ids(decisions[rid]) == {"TIME-03"}

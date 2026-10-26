"""The policy text is the source of truth: constants in code must match it (ADR-029)."""

import re

import pytest

from policy_validator import policy_constants as pc
from policy_validator.config import POLICY_DIR
from policy_validator.policy_registry import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_registry_has_all_41_rules(registry):
    assert len(registry) == 41
    assert {"ALC-01", "EXC-01", "REG-05", "TIME-04"} <= set(registry)


def test_rule_bodies_capture_follow_up_paragraphs(registry):
    assert "on every meal receipt" in registry["MEAL-01"].text
    assert "Baggage-delay exception" in registry["PERS-01"].text
    assert "Scope of ALC-01 and ALC-02" in registry["ALC-02"].text
    # A bold-led note that is not a rule must not leak into the previous rule.
    assert "Note on identification" not in registry["ALC-03"].text


@pytest.mark.parametrize("rule_id,severity", sorted(pc.SEVERITY.items()))
def test_severity_appears_in_rule_text(registry, rule_id, severity):
    assert re.search(rf"\*\*{severity}\*\*", registry[rule_id].text), rule_id


def test_health_01_prescription_severity(registry):
    assert f"**{pc.HEALTH_01_PRESCRIPTION_SEVERITY}** exception" in registry["HEALTH-01"].text


def _usd(value: float) -> str:
    return f"${value:g}"


@pytest.mark.parametrize(
    "rule_id,snippet",
    [
        ("MEAL-01", _usd(pc.MEAL_CAP_DOMESTIC_USD)),
        ("MEAL-01", _usd(pc.MEAL_CAP_INTERNATIONAL_USD)),
        ("MEAL-02", _usd(pc.MEAL_ATTENDEE_DOC_THRESHOLD_USD)),
        ("REG-02", _usd(pc.APAC_MEAL_CAP_USD)),
        ("REG-03", f"EUR {pc.EMEA_MEAL_CAP_EUR:g}"),
        ("REG-04", f"EUR {pc.EMEA_VAT_THRESHOLD_EUR:g}"),
        ("ALC-02", _usd(pc.ALCOHOL_CAP_PER_ATTENDEE_USD)),
        ("ALC-01", "two or more"),
        ("TECH-02", _usd(pc.PERIPHERAL_UNIT_CAP_USD)),
        ("GIFT-01", _usd(pc.GIFT_CAP_PER_RECIPIENT_USD)),
        ("GIFT-01", _usd(pc.GIFT_NAMED_RECIPIENT_MIN_USD)),
        ("HEALTH-01", _usd(pc.OTC_TRIP_CAP_USD)),
        ("PERS-01", _usd(pc.BAGGAGE_DELAY_ALLOWANCE_USD)),
        ("PERS-02", _usd(pc.BAGGAGE_DELAY_ALLOWANCE_USD)),
        ("LAUNDRY-01", "four or more nights"),
        ("DOC-01", _usd(pc.ITEMIZATION_THRESHOLD_USD)),
    ],
)
def test_thresholds_appear_in_rule_text(registry, rule_id, snippet):
    assert snippet in registry[rule_id].evidence, f"{snippet!r} not in {rule_id}"


def test_whole_receipt_rules_match_exc_04(registry):
    exc_04 = registry["EXC-04"].text
    for rule_id in pc.WHOLE_RECEIPT_RULES:
        assert rule_id in exc_04


def test_mcc_tiers_match_risk_table(registry):
    table = (POLICY_DIR / registry["MCC-01"].policy_doc).read_text()
    for mcc in pc.HIGH_RISK_MCCS:
        assert re.search(rf"\| {mcc} \|.*\*\*High\*\*", table)
    for mcc in pc.MEDIUM_RISK_MCCS:
        assert re.search(rf"\| {mcc} \|.*\| Medium \|", table)

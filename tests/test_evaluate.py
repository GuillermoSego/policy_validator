"""Metric definitions and the keyword baseline."""

import pytest
from sklearn.metrics import f1_score

from policy_validator.baseline import keyword_category, legacy_disposition
from policy_validator.data import load_gold
from policy_validator.evaluate import (
    Scored,
    disposition_metrics,
    evaluate,
    in_scope_ids,
    macro_f1_by_hand,
)
from policy_validator.oracle import run_oracle


@pytest.mark.parametrize(
    "y_true,y_pred",
    [
        (["a", "a", "b", "c"], ["a", "b", "b", "c"]),
        (["a", "b", "c"], ["a", "a", "a"]),  # b and c never predicted -> F1 0
        (["a", "b"], ["x", "y"]),  # predictions outside the gold set
    ],
)
def test_sklearn_macro_f1_matches_brief_definition(y_true, y_pred):
    labels = sorted(set(y_true))
    sk = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    assert sk == pytest.approx(macro_f1_by_hand(y_true, y_pred))


def test_disposition_metrics_counts_fp_and_missed():
    gold = load_gold()
    ids = in_scope_ids(gold)
    predicted = {rid: gold[rid].disposition for rid in ids}
    predicted["RCP-001"] = "review"  # should pass
    predicted["RCP-010"] = "review"  # should flag
    m = disposition_metrics(predicted, gold, ids)
    assert m["false_positives"] == {"count": 1, "of": 9, "receipts": ["RCP-001"]}
    assert m["missed_violations"]["count"] == 1
    assert m["confusion"]["pass"]["review"] == 1
    assert m["accuracy"] == pytest.approx(26 / 28)


def test_oracle_scores_perfectly():
    oracle = {r.receipt_id: r for r in run_oracle()}
    report = evaluate([Scored("oracle", oracle)])["oracle"]
    assert report["classification"]["macro_f1"] == 1.0
    assert report["disposition"]["accuracy"] == 1.0
    assert report["exceptions"]["evidence_exact"] == 1.0


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Beer battered cod & chips", "alcohol"),  # the classic keyword false positive
        ("Arnold Palmer", "food_beverage"),
        ("Weisswein 0,2l", "food_beverage"),  # English-only list misses German wine
        ("Cooking wine - Marsala 375ml", "alcohol"),
        ("Gratuity 18%", "service_fee"),
    ],
)
def test_keyword_baseline_behaves_like_a_keyword_system(text, expected):
    assert keyword_category(text, "Meals - Individual") == expected


def test_legacy_flags_on_any_restricted_keyword():
    from tests.factories import item

    assert legacy_disposition([item("L1", "alcohol", 5.0)]) == "flag"
    assert legacy_disposition([item("L1", "food_beverage", 5.0)]) == "pass"

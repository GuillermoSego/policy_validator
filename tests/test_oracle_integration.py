"""Oracle ablation (ADR-023): with gold categories, the deterministic half must be exact.

Evaluation-only use of labels: this test checks the retriever + engine + reporter, never feeds
labels to the pipeline.
"""

import pytest

from policy_validator.data import load_gold
from policy_validator.oracle import run_oracle
from policy_validator.policy_registry import load_registry
from policy_validator.retriever import CATEGORY_RULES, MCC_RULES, retrieved_ids


@pytest.fixture(scope="module")
def results():
    return {r.receipt_id: r for r in run_oracle()}


@pytest.fixture(scope="module")
def gold():
    return load_gold()


def _in_scope(gold):
    return [rid for rid, g in gold.items() if g.in_scope]


def test_oracle_dispositions_match_gold_on_all_28(results, gold):
    wrong = {rid for rid in _in_scope(gold) if results[rid].disposition != gold[rid].disposition}
    assert not wrong


def test_oracle_exceptions_and_evidence_match_gold(results, gold):
    for rid in _in_scope(gold):
        mine = {(e.rule_id, tuple(e.line_ids)) for e in results[rid].exceptions}
        expected = {(e["rule_id"], tuple(e["line_ids"])) for e in gold[rid].exceptions}
        assert mine == expected, rid


def test_oracle_review_signals_match_gold(results, gold):
    for rid in _in_scope(gold):
        mine = {s.rule_id for s in results[rid].review_signals}
        expected = {s["rule_id"] for s in gold[rid].review_signals}
        assert mine == expected, rid


def test_retriever_recall_is_complete_on_gold_rules(results, gold):
    for rid in _in_scope(gold):
        needed = {e["rule_id"] for e in gold[rid].exceptions + gold[rid].review_signals}
        assert needed <= retrieved_ids(results[rid].retrieved_rules), rid


def test_retriever_tables_reference_real_rules():
    registry = load_registry()
    for rules in (*CATEGORY_RULES.values(), *MCC_RULES.values()):
        assert set(rules) <= set(registry)


def test_every_exception_cites_policy_text(results):
    for result in results.values():
        for exc in result.exceptions:
            assert exc.evidence and exc.policy_doc.endswith(".md")


def test_oracle_matches_gold_on_all_32_including_time_rules(results, gold):
    """Stretch goal: the four timing receipts (TIME-01..TIME-03) are exact too."""
    for rid, g in gold.items():
        r = results[rid]
        assert r.disposition == g.disposition, rid
        mine = {(e.rule_id, tuple(e.line_ids)) for e in r.exceptions}
        assert mine == {(e["rule_id"], tuple(e["line_ids"])) for e in g.exceptions}, rid
        assert {s.rule_id for s in r.review_signals} == {s["rule_id"] for s in g.review_signals}

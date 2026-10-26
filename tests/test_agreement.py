"""Two-model agreement as EXC-03 confidence (ADR-043)."""

import dataclasses

from policy_validator.agreement import agreement_items, disagreements
from policy_validator.config import OUTPUTS_DIR, load_settings
from policy_validator.data import load_receipts
from policy_validator.pipeline import decide_all, run_pipeline
from policy_validator.reporter import read_results

PRIMARY = OUTPUTS_DIR / "results.jsonl"
SECONDARY = OUTPUTS_DIR / "second_model_results.jsonl"


def _load(path):
    return {r.receipt_id: r for r in read_results(path)}


def test_disagreement_zeroes_confidence_and_raises_exc_03():
    primary, secondary = _load(PRIMARY), _load(SECONDARY)
    # Make the second model call RCP-010's beer food: a genuine disagreement on a violation.
    rcp = secondary["RCP-010"]
    flipped = [
        i.model_copy(update={"category": "food_beverage"}) if i.line_id == "RCP-010-L2" else i
        for i in rcp.line_items
    ]
    secondary["RCP-010"] = rcp.model_copy(update={"line_items": flipped})

    assert [d["line_id"] for d in disagreements(primary, secondary)] == ["RCP-010-L2"]
    combined = agreement_items(primary, secondary)
    beer = next(i for i in combined["RCP-010"] if i.line_id == "RCP-010-L2")
    assert beer.confidence == 0.0 and beer.category == "alcohol"

    decided = {r.receipt_id: r for r in decide_all(load_receipts(), combined, 0.5, run="t")}
    result = decided["RCP-010"]
    assert result.exceptions == []  # ALC-01 is not raised on an uncertain item...
    assert [s.rule_id for s in result.review_signals] == ["EXC-03"]  # ...it goes to review
    assert result.disposition == "review"


def test_agreement_keeps_the_lower_confidence():
    primary, secondary = _load(PRIMARY), _load(SECONDARY)
    combined = agreement_items(primary, secondary)
    for rid, items in combined.items():
        for item, a, b in zip(
            items, primary[rid].line_items, secondary[rid].line_items, strict=True
        ):
            assert item.confidence == min(a.confidence, b.confidence)


def test_offline_replay_reproduces_committed_second_model():
    settings = dataclasses.replace(load_settings(), api_key=None, model="google/gemini-2.5-flash")
    results, llm = run_pipeline(settings)
    assert llm.usage.cache_hits == llm.usage.calls
    committed = read_results(SECONDARY)
    assert [r.model_dump(exclude={"run"}) for r in results] == [
        r.model_dump(exclude={"run"}) for r in committed
    ]

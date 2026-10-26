"""The live demo: offline, deterministic, and every scenario lands where the policy says."""

import json

import pytest

from policy_validator import demo
from policy_validator.cli import main


@pytest.fixture(scope="module")
def world():
    return demo.load_world()


def test_world_is_served_entirely_from_the_cache(world):
    assert world.llm_calls == world.cache_hits > 0
    assert world.spent_this_run == 0.0


def test_tour_runs_end_to_end_without_pausing(world, capsys):
    demo.cmd_tour(world, pause=False)
    out = capsys.readouterr().out
    for n in range(1, len(demo.SCENES) + 1):
        assert f"Scene {n} ·" in out
    assert "\033[" not in out  # no colour codes when not writing to a terminal


def test_scoreboard_matches_the_evaluation(world):
    board = demo.scoreboard(world)
    assert board["LLM pipeline + engine"] == {
        "correct_28": 28,
        "correct_32": 32,
        "false_positives": 0,
        "missed": 0,
    }
    assert board["Keyword classifier + same engine"]["correct_28"] == 24
    assert board["Legacy keyword flagging"]["correct_28"] == 18


def test_every_receipt_traces_and_matches_the_answer_key(world, capsys):
    for rid in world.receipts:
        result = demo.cmd_trace(world, rid)
        assert demo.matches_gold(result, world.gold[rid]), rid
    assert "5 REPORTER" in capsys.readouterr().out


def _after(world, rid, **change):
    return demo.whatif(world, rid, demo.Change(**change))


def test_context_decides_the_same_beer(world):
    entertainment = {"submitted_expense_type": "Client Entertainment", "attendee_count": "2"}
    assert _after(world, "RCP-010", fields=entertainment).disposition == "pass"
    apac = _after(world, "RCP-010", fields={**entertainment, "employee_country": "IN"})
    assert [e.rule_id for e in apac.exceptions] == ["REG-01"]


def test_threshold_boundary_and_pre_approval(world):
    assert _after(world, "RCP-006", usd={"L1": 200.00}).disposition == "pass"
    over = _after(world, "RCP-006", usd={"L1": 200.01})
    assert [(e.rule_id, e.severity) for e in over.exceptions] == [("TECH-02", "medium")]
    approved = _after(
        world, "RCP-006", usd={"L1": 200.01}, fields={"pre_approval_ref": "PA-2026-0999"}
    )
    assert approved.disposition == "pass"


def test_pre_approval_does_not_waive_the_baggage_delay_carve_out(world):
    result = _after(world, "RCP-027", fields={"pre_approval_ref": "PA-2026-0999"})
    assert "PERS-02" in {e.rule_id for e in result.exceptions}


def test_moving_one_receipt_breaks_the_split_for_both(world, capsys):
    result = _after(world, "RCP-021", fields={"transaction_datetime": "2026-04-28T19:40:00"})
    assert result.disposition == "pass"
    assert "RCP-020: FLAG" in capsys.readouterr().out


def test_low_confidence_turns_an_exception_into_a_review(world):
    result = _after(world, "RCP-010", confidence={"L2": 0.3})
    assert result.exceptions == []
    assert [s.rule_id for s in result.review_signals] == ["EXC-03"]


def test_item_facts_can_be_changed(world):
    result = _after(world, "RCP-018", facts={"L1": {"recipient_type": "government_official"}})
    assert result.exceptions[0].rule_id == "GIFT-04"


def test_whatif_leaves_the_world_untouched(world):
    _after(world, "RCP-006", usd={"L1": 500.0}, category={"L1": "personal_electronics"})
    assert world.receipts["RCP-006"].total_amount_usd == 189.0
    assert world.classified["RCP-006"][0].category == "computer_accessory"


@pytest.mark.parametrize(
    "change",
    [
        {"fields": {"no_such_field": "1"}},
        {"fields": {"attendee_count": "many"}},
        {"usd": {"L9": 1.0}},
        {"category": {"L1": "wine"}},
        {"confidence": {"L1": 1.5}},
        {"facts": {"L1": {"no_such_fact": "x"}}},
    ],
)
def test_bad_changes_are_rejected_with_a_message(world, change):
    with pytest.raises(demo.DemoError):
        demo.apply_change(world, "RCP-010", demo.Change(**change))


class CannedLLM:
    """Answers the normaliser and classifier without a network."""

    model = "canned"
    usage = None

    def __init__(self, categories):
        self.categories = categories
        self.stages = []

    def complete_json(self, *, stage, user, validate, **kwargs):
        self.stages.append(stage)
        items = json.loads(user)["items"]
        if stage == "normaliser":
            return validate({"items": [{"line_id": i["line_id"], "text_en": "x"} for i in items]})
        rows = [
            {
                "line_id": i["line_id"],
                "category": self.categories[i["line_id"]],
                "confidence": 0.9,
                "is_gift": False,
                "recipient": None,
                "recipient_type": "self",
                "is_prescription": False,
                "is_mobile_handset": False,
                "is_entertainment_venue": False,
                "rationale": "canned",
            }
            for i in items
        ]
        return validate({"items": rows})


def test_custom_receipt_runs_the_full_pipeline():
    categories = {f"DEMO-001-L{n}": "food_beverage" for n in range(1, 6)}
    categories["DEMO-001-L3"] = "alcohol"
    categories["DEMO-001-L5"] = "service_fee"
    llm = CannedLLM(categories)
    result = demo.cmd_custom(demo.EXAMPLE_CUSTOM_RECEIPT, llm)
    assert llm.stages == ["normaliser", "classifier"]  # one Spanish line -> one translation call
    assert [(e.rule_id, e.line_ids) for e in result.exceptions] == [("ALC-01", ["DEMO-001-L3"])]


def test_cli_entry_points(capsys):
    assert main(["demo", "tour", "--scene", "1", "--no-pause"]) == 0
    assert main(["demo", "whatif", "RCP-031", "--set", "trip_nights=5"]) == 0
    assert main(["demo", "rule", "EXC-01"]) == 0
    assert main(["demo", "whatif", "RCP-010", "--usd", "nonsense"]) == 1
    out = capsys.readouterr().out
    assert "Names lie" in out and "after    PASS" in out and "EXC-01 — Receipt disposition" in out

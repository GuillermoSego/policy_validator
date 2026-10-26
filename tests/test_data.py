from typing import get_args

from policy_validator.data import load_gold, load_receipts, load_taxonomy
from policy_validator.models import Category


def test_pipeline_input_carries_no_labels():
    for receipt in load_receipts():
        dumped = receipt.model_dump()
        assert "labels" not in dumped and "notes" not in dumped
        assert all("labels" not in item for item in dumped["line_items"])


def test_dataset_counts_match_the_brief():
    receipts = load_receipts()
    gold = load_gold()
    assert len(receipts) == 32
    assert sum(len(r.line_items) for r in receipts) == 79
    in_scope = [g for g in gold.values() if g.in_scope]
    assert len(in_scope) == 28
    assert sum(len(g.item_categories) for g in in_scope) == 65
    dispositions = [g.disposition for g in in_scope]
    assert dispositions.count("pass") == 9
    assert dispositions.count("flag") == 16
    assert dispositions.count("review") == 3


def test_taxonomy_file_matches_category_type():
    taxonomy = load_taxonomy()
    assert set(taxonomy) == set(get_args(Category))
    assert taxonomy["alcohol"].restricted
    assert not taxonomy["food_beverage"].restricted

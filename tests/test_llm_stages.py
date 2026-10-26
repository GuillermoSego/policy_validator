"""Normaliser, classifier and pipeline behaviour without network access."""

import dataclasses

from policy_validator.classifier import classify_receipt
from policy_validator.config import OUTPUTS_DIR, load_settings
from policy_validator.data import load_receipts
from policy_validator.llm import LLMError
from policy_validator.normaliser import clean, normalise_receipt
from policy_validator.pipeline import run_pipeline
from policy_validator.reporter import read_results


class ExplodingLLM:
    """Fails every call — proves a stage did not call the model, or falls back when it does."""

    model = "none"

    def __init__(self):
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        raise LLMError("boom")


def _receipt(receipt_id):
    return next(r for r in load_receipts() if r.receipt_id == receipt_id)


def test_clean_normalises_unicode_and_whitespace():
    assert clean("  iPad　Air  11インチ ") == "iPad Air 11インチ"


def test_english_receipt_never_calls_the_model():
    llm = ExplodingLLM()
    lines = normalise_receipt(_receipt("RCP-001"), llm)
    assert llm.calls == 0
    assert not any(line.translated for line in lines.values())


def test_failed_translation_falls_back_to_original_text():
    lines = normalise_receipt(_receipt("RCP-025"), ExplodingLLM())
    assert lines["RCP-025-L2"].text_en == "Weisswein 0,2l"


def test_non_itemized_receipt_is_other_without_the_model():
    receipt = _receipt("RCP-023")
    llm = ExplodingLLM()
    items = classify_receipt(receipt, normalise_receipt(receipt, None), llm)
    assert llm.calls == 0
    assert [(i.category, i.confidence) for i in items] == [("other", 1.0)]


def test_classifier_failure_becomes_uncertain_other():
    receipt = _receipt("RCP-010")
    items = classify_receipt(receipt, normalise_receipt(receipt, None), ExplodingLLM())
    assert {(i.category, i.confidence) for i in items} == {("other", 0.0)}


def test_offline_replay_reproduces_committed_results():
    """The committed cache is complete: no key needed, identical output (ADR-007)."""
    settings = dataclasses.replace(load_settings(), api_key=None)
    results, llm = run_pipeline(settings)
    assert llm.usage.cache_hits == llm.usage.calls
    committed = read_results(OUTPUTS_DIR / "results.jsonl")
    assert [r.model_dump() for r in results] == [r.model_dump() for r in committed]

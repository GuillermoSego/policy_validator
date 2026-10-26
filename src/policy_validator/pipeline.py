"""End-to-end pipeline: normalise -> classify -> retrieve -> engine -> report."""

from __future__ import annotations

import json
from pathlib import Path

from .classifier import classify_receipt
from .config import Settings
from .data import load_receipts
from .engine import evaluate_batch
from .llm import LLMClient
from .models import ClassifiedItem, Receipt, ReceiptResult
from .normaliser import normalise_receipt
from .prompts import CLASSIFIER_VERSION, NORMALISER_VERSION
from .reporter import build_result
from .retriever import retrieve, retrieved_ids

PROMPT_VERSIONS = {"normaliser": NORMALISER_VERSION, "classifier": CLASSIFIER_VERSION}


def classify_all(receipts: list[Receipt], llm: LLMClient) -> dict[str, list[ClassifiedItem]]:
    classified = {}
    for receipt in receipts:
        normalised = normalise_receipt(receipt, llm)
        classified[receipt.receipt_id] = classify_receipt(receipt, normalised, llm)
    return classified


def decide_all(
    receipts: list[Receipt],
    classified: dict[str, list[ClassifiedItem]],
    threshold: float,
    *,
    run: str,
    model_id: str | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> list[ReceiptResult]:
    """The deterministic half, shared by the pipeline, the oracle and the baseline."""
    retrieved = {r.receipt_id: retrieve(r, classified[r.receipt_id]) for r in receipts}
    decisions = evaluate_batch(
        receipts,
        classified,
        threshold,
        {rid: retrieved_ids(rules) for rid, rules in retrieved.items()},
    )
    return [
        build_result(
            r,
            classified[r.receipt_id],
            decisions[r.receipt_id],
            retrieved[r.receipt_id],
            run=run,
            model_id=model_id,
            prompt_versions=prompt_versions,
        )
        for r in receipts
    ]


def run_pipeline(settings: Settings) -> tuple[list[ReceiptResult], LLMClient]:
    receipts = load_receipts()
    llm = LLMClient(settings)
    classified = classify_all(receipts, llm)
    results = decide_all(
        receipts,
        classified,
        settings.confidence_threshold,
        run="pipeline",
        model_id=settings.model,
        prompt_versions=PROMPT_VERSIONS,
    )
    return results, llm


def write_manifest(path: Path, settings: Settings, llm: LLMClient) -> None:
    """Deterministic run summary: the cost is that of the cached responses the run used, so it
    equals the original spend no matter how many times the run is replayed from cache."""
    u = llm.usage
    manifest = {
        "model": settings.model,
        "temperature": settings.temperature,
        "confidence_threshold": settings.confidence_threshold,
        "prompt_versions": PROMPT_VERSIONS,
        "llm_calls": u.calls,
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "cost_usd": round(u.cost_usd, 6),
        "by_stage": {
            stage: {k: round(v, 6) if isinstance(v, float) else v for k, v in s.items()}
            for stage, s in sorted(u.by_stage.items())
        },
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

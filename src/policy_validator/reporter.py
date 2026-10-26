"""5. Exception reporter — reviewer-readable findings citing policy text.

Turns the engine's decisions into the output format from the brief: each exception names its rule,
the policy document it comes from, its severity, the lines it concerns, the policy text behind it
(`evidence`) and a concrete `explanation` with the numbers that triggered it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import OUT_OF_SCOPE_RECEIPTS
from .engine import Decision
from .models import (
    ClassifiedItem,
    PolicyException,
    Receipt,
    ReceiptResult,
    RetrievedRule,
    ReviewSignal,
)
from .policy_registry import load_registry


def build_result(
    receipt: Receipt,
    items: list[ClassifiedItem],
    decision: Decision,
    retrieved: list[RetrievedRule],
    *,
    run: str,
    model_id: str | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> ReceiptResult:
    registry = load_registry()
    exceptions = [
        PolicyException(
            rule_id=hit.rule_id,
            policy_doc=registry[hit.rule_id].policy_doc,
            severity=hit.severity,
            line_ids=list(hit.line_ids),
            evidence=registry[hit.rule_id].evidence,
            explanation=hit.explanation,
        )
        for hit in decision.exceptions
    ]
    signals = [
        ReviewSignal(
            rule_id=hit.rule_id,
            policy_doc=registry[hit.rule_id].policy_doc,
            reason=hit.explanation,
            line_ids=list(hit.line_ids),
        )
        for hit in decision.signals
    ]
    return ReceiptResult(
        receipt_id=receipt.receipt_id,
        disposition=decision.disposition,
        line_items=items,
        exceptions=exceptions,
        review_signals=signals,
        retrieved_rules=retrieved,
        in_scope=receipt.receipt_id not in OUT_OF_SCOPE_RECEIPTS,
        run=run,
        model_id=model_id,
        prompt_versions=prompt_versions or {},
    )


def write_results(results: list[ReceiptResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for result in results:
            fh.write(result.model_dump_json() + "\n")


def read_results(path: Path) -> list[ReceiptResult]:
    with path.open(encoding="utf-8") as fh:
        return [ReceiptResult.model_validate(json.loads(line)) for line in fh if line.strip()]


def format_text(result: ReceiptResult) -> str:
    """Plain-text report for one receipt, for the CLI."""
    lines = [f"{result.receipt_id}: {result.disposition.upper()}"]
    for exc in result.exceptions:
        cited = ", ".join(exc.line_ids) or "whole receipt"
        lines.append(f"  [{exc.severity}] {exc.rule_id} ({cited}) — {exc.explanation}")
    for sig in result.review_signals:
        lines.append(f"  [signal] {sig.rule_id} — {sig.reason}")
    return "\n".join(lines)

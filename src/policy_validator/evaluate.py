"""Evaluation on the 28 in-scope receipts (brief, Part 3).

Labels are read here and only here (plus the oracle). Every metric is computed for each system —
pipeline, keyword baseline, oracle ablation — from the committed result files, so evaluation never
calls a model.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from sklearn.metrics import f1_score

from .data import GoldReceipt, is_restricted, load_gold, load_receipts
from .models import ClassifiedItem, ReceiptResult

DISPOSITIONS = ("flag", "review", "pass")


@dataclass(frozen=True)
class Scored:
    system: str
    results: dict[str, ReceiptResult]


def in_scope_ids(gold: dict[str, GoldReceipt]) -> list[str]:
    return [rid for rid, g in gold.items() if g.in_scope]


# --- Classification ----------------------------------------------------------------------------


def classification_metrics(results: dict[str, ReceiptResult], gold, ids) -> dict:
    y_true, y_pred = [], []
    for rid in ids:
        for item in results[rid].line_items:
            y_true.append(gold[rid].item_categories[item.line_id])
            y_pred.append(item.category)
    gold_categories = sorted(set(y_true))
    per_category = f1_score(y_true, y_pred, labels=gold_categories, average=None, zero_division=0)
    r_true = [is_restricted(c) for c in y_true]
    r_pred = [is_restricted(c) for c in y_pred]
    return {
        "items": len(y_true),
        "accuracy": sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true),
        "macro_f1": float(per_category.mean()),
        "per_category_f1": {
            c: round(float(f), 4) for c, f in zip(gold_categories, per_category, strict=True)
        },
        "restricted_f1": float(f1_score(r_true, r_pred, pos_label=True, zero_division=0)),
        "errors": [
            {
                "line_id": item.line_id,
                "gold": gold[rid].item_categories[item.line_id],
                "predicted": item.category,
                "confidence": item.confidence,
                "text": item.description_raw,
            }
            for rid in ids
            for item in results[rid].line_items
            if item.category != gold[rid].item_categories[item.line_id]
        ],
    }


def macro_f1_by_hand(y_true: list[str], y_pred: list[str]) -> float:
    """Reference implementation of the brief's definition, used to check sklearn in tests."""
    scores = []
    for c in sorted(set(y_true)):
        tp = sum(t == c and p == c for t, p in zip(y_true, y_pred, strict=True))
        fp = sum(t != c and p == c for t, p in zip(y_true, y_pred, strict=True))
        fn = sum(t == c and p != c for t, p in zip(y_true, y_pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores)


# --- Dispositions --------------------------------------------------------------------------------


def disposition_metrics(predicted: dict[str, str], gold, ids) -> dict:
    matrix = {g: {p: 0 for p in DISPOSITIONS} for g in DISPOSITIONS}
    for rid in ids:
        matrix[gold[rid].disposition][predicted[rid]] += 1
    should_pass = [rid for rid in ids if gold[rid].disposition == "pass"]
    should_flag = [rid for rid in ids if gold[rid].disposition == "flag"]
    return {
        "confusion": matrix,  # rows = gold, columns = predicted
        "accuracy": sum(predicted[rid] == gold[rid].disposition for rid in ids) / len(ids),
        "false_positives": {
            "count": sum(predicted[rid] != "pass" for rid in should_pass),
            "of": len(should_pass),
            "receipts": [rid for rid in should_pass if predicted[rid] != "pass"],
        },
        "missed_violations": {
            "count": sum(predicted[rid] != "flag" for rid in should_flag),
            "of": len(should_flag),
            "receipts": [rid for rid in should_flag if predicted[rid] != "flag"],
        },
        "wrong": [
            {"receipt_id": rid, "gold": gold[rid].disposition, "predicted": predicted[rid]}
            for rid in ids
            if predicted[rid] != gold[rid].disposition
        ],
    }


# --- Exceptions, evidence, signals, retrieval ----------------------------------------------------


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def exception_metrics(results: dict[str, ReceiptResult], gold, ids) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    matched = exact_evidence = 0
    sig_tp = sig_fp = sig_fn = 0
    retrieval_hits = retrieval_needed = 0
    for rid in ids:
        mine = {e.rule_id: tuple(e.line_ids) for e in results[rid].exceptions}
        expected = {e["rule_id"]: tuple(e["line_ids"]) for e in gold[rid].exceptions}
        for rule_id in mine.keys() | expected.keys():
            if rule_id in mine and rule_id in expected:
                counts[rule_id]["tp"] += 1
                matched += 1
                exact_evidence += mine[rule_id] == expected[rule_id]
            elif rule_id in mine:
                counts[rule_id]["fp"] += 1
            else:
                counts[rule_id]["fn"] += 1

        my_sig = {s.rule_id for s in results[rid].review_signals}
        gold_sig = {s["rule_id"] for s in gold[rid].review_signals}
        sig_tp += len(my_sig & gold_sig)
        sig_fp += len(my_sig - gold_sig)
        sig_fn += len(gold_sig - my_sig)

        needed = expected.keys() | gold_sig
        retrieved = {r.rule_id for r in results[rid].retrieved_rules}
        retrieval_needed += len(needed)
        retrieval_hits += len(needed & retrieved)

    totals = Counter()
    for c in counts.values():
        totals.update(c)
    return {
        "overall": _prf(totals["tp"], totals["fp"], totals["fn"]),
        "per_rule": {rule: _prf(c["tp"], c["fp"], c["fn"]) for rule, c in sorted(counts.items())},
        "evidence_exact": exact_evidence / matched if matched else None,
        "review_signals": _prf(sig_tp, sig_fp, sig_fn),
        "retriever_recall": retrieval_hits / retrieval_needed if retrieval_needed else None,
    }


# --- Confidence sensitivity (ADR-004) ------------------------------------------------------------


def threshold_sensitivity(results: dict[str, ReceiptResult], gold, ids, thresholds) -> dict:
    """Re-decide the pipeline's own classifications at other thresholds — no model calls."""
    from .pipeline import decide_all

    receipts = load_receipts()
    classified: dict[str, list[ClassifiedItem]] = {rid: r.line_items for rid, r in results.items()}
    out = {}
    for t in thresholds:
        decided = {r.receipt_id: r for r in decide_all(receipts, classified, t, run="sensitivity")}
        exc_03 = sum(1 for rid in ids for s in decided[rid].review_signals if s.rule_id == "EXC-03")
        out[str(t)] = {
            "disposition_accuracy": sum(
                decided[rid].disposition == gold[rid].disposition for rid in ids
            )
            / len(ids),
            "exc_03_signals": exc_03,
            "items_below_threshold": sum(
                1 for rid in ids for i in results[rid].line_items if i.confidence < t
            ),
        }
    return out


def confidence_summary(results: dict[str, ReceiptResult], gold, ids) -> dict:
    correct, wrong = [], []
    for rid in ids:
        for item in results[rid].line_items:
            ok = item.category == gold[rid].item_categories[item.line_id]
            (correct if ok else wrong).append(item.confidence)
    return {
        "min_confidence_correct": min(correct) if correct else None,
        "max_confidence_wrong": max(wrong) if wrong else None,
        "histogram": dict(sorted(Counter(round(c, 2) for c in correct + wrong).items())),
    }


# --- Orchestration -------------------------------------------------------------------------------


def evaluate(
    systems: list[Scored], legacy: dict[str, str] | None = None, thresholds=(0.4, 0.5, 0.6, 0.7)
) -> dict:
    gold = load_gold()
    ids = in_scope_ids(gold)
    report: dict = {"scope": {"receipts": len(ids), "out_of_scope": sorted(set(gold) - set(ids))}}
    for scored in systems:
        r = scored.results
        report[scored.system] = {
            "classification": classification_metrics(r, gold, ids),
            "disposition": disposition_metrics({k: v.disposition for k, v in r.items()}, gold, ids),
            "exceptions": exception_metrics(r, gold, ids),
        }
        if scored.system == "pipeline":
            report[scored.system]["threshold_sensitivity"] = threshold_sensitivity(
                r, gold, ids, thresholds
            )
            report[scored.system]["confidence"] = confidence_summary(r, gold, ids)
    if legacy is not None:
        report["legacy_keyword_flagging"] = {"disposition": disposition_metrics(legacy, gold, ids)}
    return report


# --- Markdown rendering --------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def render_markdown(report: dict) -> str:
    systems = [s for s in ("pipeline", "baseline", "oracle") if s in report]
    names = {
        "pipeline": "Pipeline (LLM)",
        "baseline": "Keyword baseline + same engine",
        "oracle": "Oracle ablation (gold categories)",
    }
    lines = [
        "# Metrics (generated)",
        "",
        "Generated by `validator evaluate` from the committed result files. Do not edit by hand.",
        f"Scope: {report['scope']['receipts']} receipts; out of scope: "
        f"{', '.join(report['scope']['out_of_scope'])}.",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(names[s] for s in systems) + " |",
        "|---|" + "---|" * len(systems),
    ]

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(fn(report[s]) for s in systems) + " |")

    row("Category macro F1 (65 items)", lambda r: f"{r['classification']['macro_f1']:.3f}")
    row("Category accuracy", lambda r: _pct(r["classification"]["accuracy"]))
    row("Restricted F1", lambda r: f"{r['classification']['restricted_f1']:.3f}")
    row("Disposition accuracy", lambda r: _pct(r["disposition"]["accuracy"]))
    row(
        "False positives (of 9 pass)",
        lambda r: f"{r['disposition']['false_positives']['count']}",
    )
    row(
        "Missed violations (of 16 flag)",
        lambda r: f"{r['disposition']['missed_violations']['count']}",
    )
    row("Exception precision", lambda r: _pct(r["exceptions"]["overall"]["precision"]))
    row("Exception recall", lambda r: _pct(r["exceptions"]["overall"]["recall"]))
    row("Evidence exact (matched exceptions)", lambda r: _pct(r["exceptions"]["evidence_exact"]))
    row("Review-signal precision", lambda r: _pct(r["exceptions"]["review_signals"]["precision"]))
    row("Review-signal recall", lambda r: _pct(r["exceptions"]["review_signals"]["recall"]))
    row("Retriever recall (gold rules)", lambda r: _pct(r["exceptions"]["retriever_recall"]))

    if "legacy_keyword_flagging" in report:
        d = report["legacy_keyword_flagging"]["disposition"]
        lines += [
            "",
            "Legacy keyword flagging (no engine — flag on any restricted keyword): disposition "
            f"accuracy {_pct(d['accuracy'])}, false positives {d['false_positives']['count']}/9 "
            f"({', '.join(d['false_positives']['receipts']) or 'none'}), missed violations "
            f"{d['missed_violations']['count']}/16 "
            f"({', '.join(d['missed_violations']['receipts']) or 'none'}).",
        ]

    for s in systems:
        m = report[s]["disposition"]["confusion"]
        lines += [
            "",
            f"## Disposition confusion — {names[s]}",
            "",
            "| gold \\ predicted | flag | review | pass |",
            "|---|---|---|---|",
        ]
        for g in DISPOSITIONS:
            lines.append(f"| **{g}** | " + " | ".join(str(m[g][p]) for p in DISPOSITIONS) + " |")
        wrong = report[s]["disposition"]["wrong"]
        if wrong:
            lines.append("")
            lines.append(
                "Wrong: "
                + ", ".join(f"{w['receipt_id']} ({w['gold']}→{w['predicted']})" for w in wrong)
            )

    for s in systems:
        errors = report[s]["classification"]["errors"]
        lines += ["", f"## Category errors — {names[s]}", ""]
        if not errors:
            lines.append("None.")
            continue
        lines += ["| line | text | gold | predicted |", "|---|---|---|---|"]
        lines += [
            f"| {e['line_id']} | {e['text']} | {e['gold']} | {e['predicted']} |" for e in errors
        ]

    for s in systems:
        lines += [
            "",
            f"## Per-rule exceptions — {names[s]}",
            "",
            "| rule | TP | FP | FN | precision | recall |",
            "|---|---|---|---|---|---|",
        ]
        for rule, m in report[s]["exceptions"]["per_rule"].items():
            lines.append(
                f"| {rule} | {m['tp']} | {m['fp']} | {m['fn']} | {_pct(m['precision'])} "
                f"| {_pct(m['recall'])} |"
            )

    if "threshold_sensitivity" in report.get("pipeline", {}):
        lines += [
            "",
            "## EXC-03 threshold sensitivity — pipeline",
            "",
            "| threshold | items below | EXC-03 signals | disposition accuracy |",
            "|---|---|---|---|",
        ]
        for t, m in report["pipeline"]["threshold_sensitivity"].items():
            lines.append(
                f"| {t} | {m['items_below_threshold']} | {m['exc_03_signals']} "
                f"| {_pct(m['disposition_accuracy'])} |"
            )
        c = report["pipeline"]["confidence"]
        lines += [
            "",
            f"Lowest confidence on a correct item: {c['min_confidence_correct']}; highest "
            f"confidence on a wrong item: {c['max_confidence_wrong']}. Confidence histogram: "
            + ", ".join(f"{k}: {v}" for k, v in c["histogram"].items())
            + ".",
        ]
    return "\n".join(lines) + "\n"

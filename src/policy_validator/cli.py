"""Command-line entry point: `validator <command>` (ADR-009)."""

from __future__ import annotations

import argparse
import sys

from .config import OUTPUTS_DIR, load_settings
from .reporter import format_text, write_results

RESULTS_PATH = OUTPUTS_DIR / "results.jsonl"
ORACLE_PATH = OUTPUTS_DIR / "oracle_results.jsonl"
BASELINE_PATH = OUTPUTS_DIR / "baseline_results.jsonl"
ABLATION_PATH = OUTPUTS_DIR / "ablation_no_examples_results.jsonl"
ABLATION_MANIFEST_PATH = OUTPUTS_DIR / "ablation_no_examples_manifest.json"
SECOND_MODEL = "google/gemini-2.5-flash"
SECOND_MODEL_PATH = OUTPUTS_DIR / "second_model_results.jsonl"
SECOND_MODEL_MANIFEST_PATH = OUTPUTS_DIR / "second_model_manifest.json"
AGREEMENT_PATH = OUTPUTS_DIR / "agreement_results.jsonl"
MANIFEST_PATH = OUTPUTS_DIR / "run_manifest.json"
METRICS_JSON = OUTPUTS_DIR / "metrics.json"
METRICS_MD = OUTPUTS_DIR / "metrics.md"


def cmd_run(args: argparse.Namespace) -> int:
    from .llm import BudgetExceeded, CacheMiss
    from .pipeline import run_pipeline, write_manifest

    settings = load_settings()
    mode = "online" if settings.api_key else "offline (cache only)"
    print(f"model {settings.model} · threshold {settings.confidence_threshold} · {mode}")
    try:
        results, llm = run_pipeline(settings)
    except (BudgetExceeded, CacheMiss) as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 1
    write_results(results, RESULTS_PATH)
    write_manifest(MANIFEST_PATH, settings, llm)
    if args.verbose:
        print("\n".join(format_text(r) for r in results))
    u = llm.usage
    print(
        f"{len(results)} receipts -> {RESULTS_PATH}\n"
        f"llm calls {u.calls} (cache hits {u.cache_hits}) · spent this run ${u.new_cost_usd:.4f}"
        f" · cost of responses used ${u.cost_usd:.4f}"
    )
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    from .oracle import run_oracle

    results = run_oracle(load_settings().confidence_threshold)
    write_results(results, ORACLE_PATH)
    if args.verbose:
        print("\n".join(format_text(r) for r in results))
    print(f"oracle (evaluation-only ablation): {len(results)} receipts -> {ORACLE_PATH}")
    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    from .llm import BudgetExceeded, CacheMiss
    from .pipeline import ABLATION_PROMPT_VERSIONS, run_pipeline, write_manifest

    settings = load_settings()
    try:
        results, llm = run_pipeline(settings, identification_examples=False)
    except (BudgetExceeded, CacheMiss) as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 1
    write_results(results, ABLATION_PATH)
    write_manifest(ABLATION_MANIFEST_PATH, settings, llm, ABLATION_PROMPT_VERSIONS)
    u = llm.usage
    print(
        f"prompt ablation (no identification examples): {len(results)} receipts -> "
        f"{ABLATION_PATH}\nllm calls {u.calls} (cache hits {u.cache_hits}) · spent this run "
        f"${u.new_cost_usd:.4f}"
    )
    return 0


def cmd_crossmodel(args: argparse.Namespace) -> int:
    import dataclasses

    from .agreement import agreement_items
    from .data import load_receipts
    from .llm import BudgetExceeded, CacheMiss
    from .pipeline import PROMPT_VERSIONS, decide_all, run_pipeline, write_manifest
    from .reporter import read_results

    if not RESULTS_PATH.exists():
        print(f"missing {RESULTS_PATH}; run `validator run` first", file=sys.stderr)
        return 1
    settings = dataclasses.replace(load_settings(), model=args.model)
    try:
        results, llm = run_pipeline(settings)
    except (BudgetExceeded, CacheMiss) as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 1
    results = [r.model_copy(update={"run": "second_model"}) for r in results]
    write_results(results, SECOND_MODEL_PATH)
    write_manifest(SECOND_MODEL_MANIFEST_PATH, settings, llm)

    primary = {r.receipt_id: r for r in read_results(RESULTS_PATH)}
    secondary = {r.receipt_id: r for r in results}
    combined = decide_all(
        load_receipts(),
        agreement_items(primary, secondary),
        settings.confidence_threshold,
        run="agreement",
        model_id=f"{next(iter(primary.values())).model_id} + {args.model}",
        prompt_versions=PROMPT_VERSIONS,
    )
    write_results(combined, AGREEMENT_PATH)
    u = llm.usage
    print(
        f"second model {args.model}: {len(results)} receipts -> {SECOND_MODEL_PATH}\n"
        f"two-model agreement -> {AGREEMENT_PATH}\n"
        f"llm calls {u.calls} (cache hits {u.cache_hits}) · spent this run ${u.new_cost_usd:.4f}"
    )
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from .baseline import classify_receipt
    from .data import load_receipts
    from .pipeline import decide_all

    receipts = load_receipts()
    classified = {r.receipt_id: classify_receipt(r) for r in receipts}
    threshold = load_settings().confidence_threshold
    results = decide_all(receipts, classified, threshold, run="baseline")
    write_results(results, BASELINE_PATH)
    print(f"keyword baseline: {len(results)} receipts -> {BASELINE_PATH}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    import json

    from .baseline import legacy_disposition
    from .evaluate import Scored, evaluate, render_markdown
    from .reporter import read_results

    systems = []
    for name, path in (
        ("pipeline", RESULTS_PATH),
        ("baseline", BASELINE_PATH),
        ("oracle", ORACLE_PATH),
    ):
        if not path.exists():
            print(f"missing {path}; run `validator {name if name != 'pipeline' else 'run'}` first")
            return 1
        systems.append(Scored(name, {r.receipt_id: r for r in read_results(path)}))
    for name, path in (
        ("ablation", ABLATION_PATH),  # ADR-042
        ("second_model", SECOND_MODEL_PATH),  # ADR-043
        ("agreement", AGREEMENT_PATH),  # ADR-043
    ):
        if path.exists():  # optional experiments
            systems.append(Scored(name, {r.receipt_id: r for r in read_results(path)}))
    baseline = systems[1].results
    legacy = {rid: legacy_disposition(r.line_items) for rid, r in baseline.items()}

    report = evaluate(systems, legacy)
    METRICS_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    METRICS_MD.write_text(render_markdown(report), encoding="utf-8")
    for name in [s.system for s in systems]:
        c, d = report[name]["classification"], report[name]["disposition"]
        print(
            f"{name:9s} macro-F1 {c['macro_f1']:.3f} · restricted-F1 {c['restricted_f1']:.3f} · "
            f"disposition {d['accuracy']:.1%} · FP {d['false_positives']['count']}/9 · "
            f"missed {d['missed_violations']['count']}/16"
        )
    print(f"-> {METRICS_JSON}, {METRICS_MD}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline on every receipt")
    run.add_argument("-v", "--verbose", action="store_true")
    run.set_defaults(func=cmd_run)

    oracle = sub.add_parser("oracle", help="engine on gold categories (evaluation-only ablation)")
    oracle.add_argument("-v", "--verbose", action="store_true")
    oracle.set_defaults(func=cmd_oracle)

    sub.add_parser(
        "ablation", help="pipeline with the classifier prompt's examples removed (ADR-042)"
    ).set_defaults(func=cmd_ablation)
    cross = sub.add_parser(
        "crossmodel", help="second model + two-model agreement as EXC-03 confidence (ADR-043)"
    )
    cross.add_argument("--model", default=SECOND_MODEL)
    cross.set_defaults(func=cmd_crossmodel)
    sub.add_parser("baseline", help="keyword baseline through the same engine").set_defaults(
        func=cmd_baseline
    )
    sub.add_parser("evaluate", help="metrics on the 28 in-scope receipts").set_defaults(
        func=cmd_evaluate
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

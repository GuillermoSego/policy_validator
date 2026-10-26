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


def _pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    pairs = {}
    for value in values or []:
        key, sep, rest = value.partition("=")
        if not sep or not key:
            raise ValueError(f"{flag} expects KEY=VALUE, got {value!r}")
        pairs[key.strip()] = rest.strip()
    return pairs


def cmd_demo(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import demo
    from .llm import BudgetExceeded, CacheMiss

    action = args.demo_command or "tour"
    try:
        if action == "custom":
            demo.cmd_custom(Path(args.path))
            return 0
        if action == "rule":
            print(demo.rule_text(args.rule_id))
            return 0
        world = demo.load_world()
        if action == "tour":
            demo.cmd_tour(world, getattr(args, "scene", None), not getattr(args, "no_pause", False))
        elif action == "list":
            demo.cmd_list(world)
        elif action == "trace":
            demo.cmd_trace(world, args.receipt_id, show_gold=not args.no_gold)
        elif action == "whatif":
            facts: dict[str, dict[str, str]] = {}
            for key, value in _pairs(args.fact, "--fact").items():
                line, dot, name = key.partition(".")
                if not dot:
                    raise ValueError(f"--fact expects LINE.fact=VALUE, got {key!r}")
                facts.setdefault(line, {})[name] = value
            change = demo.Change(
                fields=_pairs(args.set, "--set"),
                usd={k: float(v) for k, v in _pairs(args.usd, "--usd").items()},
                category=_pairs(args.category, "--category"),
                confidence={
                    k: float(v) for k, v in _pairs(args.confidence, "--confidence").items()
                },
                facts=facts,
            )
            if args.trace:
                demo.cmd_trace(world, args.receipt_id, show_gold=False)
            demo.whatif(world, args.receipt_id, change)
            print()
    except CacheMiss:
        print(
            "not cached and no OPENROUTER_API_KEY set: run it once with the key in .env, after "
            "which it replays offline from .demo_cache/",
            file=sys.stderr,
        )
        return 1
    except (BudgetExceeded, ValueError, FileNotFoundError) as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1
    return 0


def _add_demo_parser(sub) -> None:
    demo = sub.add_parser(
        "demo",
        help="live demo: guided tour, trace, what-if experiments, custom receipt",
        description="Live demo. Everything except `custom` runs offline from the committed cache.",
    )
    demo.set_defaults(func=cmd_demo, demo_command=None)
    actions = demo.add_subparsers(dest="demo_command")

    tour = actions.add_parser("tour", help="guided tour in eight scenes (the default)")
    tour.add_argument("--scene", type=int, help="run only this scene (1-8)")
    tour.add_argument("--no-pause", action="store_true", help="do not wait for Enter")

    actions.add_parser("list", help="every receipt on one line")

    trace = actions.add_parser("trace", help="one receipt through the five stages")
    trace.add_argument("receipt_id")
    trace.add_argument("--no-gold", action="store_true", help="hide the answer key")

    whatif = actions.add_parser(
        "whatif",
        help="change a receipt and re-decide",
        description=(
            "Re-run retriever, engine and EXC-01 on an edited receipt. Item classifications are "
            "reused from the cache. Lines may be written short: L2 means <receipt>-L2."
        ),
    )
    whatif.add_argument("receipt_id")
    whatif.add_argument("--set", action="append", metavar="FIELD=VALUE", help="receipt field")
    whatif.add_argument("--usd", action="append", metavar="LINE=AMOUNT", help="line USD amount")
    whatif.add_argument("--category", action="append", metavar="LINE=CATEGORY")
    whatif.add_argument("--confidence", action="append", metavar="LINE=0..1")
    whatif.add_argument("--fact", action="append", metavar="LINE.FACT=VALUE", help="item fact")
    whatif.add_argument("--trace", action="store_true", help="show the full trace first")

    custom = actions.add_parser(
        "custom", help="your own receipt through the full pipeline (uses the API key)"
    )
    custom.add_argument("path", nargs="?", default="demo/custom_receipt.json")

    rule = actions.add_parser("rule", help="print a rule's policy text")
    rule.add_argument("rule_id")


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
    _add_demo_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

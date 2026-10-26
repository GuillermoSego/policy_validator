"""Command-line entry point: `validator <command>` (ADR-009)."""

from __future__ import annotations

import argparse
import sys

from .config import OUTPUTS_DIR, load_settings
from .reporter import format_text, write_results

RESULTS_PATH = OUTPUTS_DIR / "results.jsonl"
ORACLE_PATH = OUTPUTS_DIR / "oracle_results.jsonl"
MANIFEST_PATH = OUTPUTS_DIR / "run_manifest.json"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline on every receipt")
    run.add_argument("-v", "--verbose", action="store_true")
    run.set_defaults(func=cmd_run)

    oracle = sub.add_parser("oracle", help="engine on gold categories (evaluation-only ablation)")
    oracle.add_argument("-v", "--verbose", action="store_true")
    oracle.set_defaults(func=cmd_oracle)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

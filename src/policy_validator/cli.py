"""Command-line entry point: `validator <command>` (ADR-009)."""

from __future__ import annotations

import argparse
import sys

from .config import OUTPUTS_DIR, load_settings
from .reporter import format_text, write_results

ORACLE_PATH = OUTPUTS_DIR / "oracle_results.jsonl"


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

    oracle = sub.add_parser("oracle", help="engine on gold categories (evaluation-only ablation)")
    oracle.add_argument("-v", "--verbose", action="store_true")
    oracle.set_defaults(func=cmd_oracle)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

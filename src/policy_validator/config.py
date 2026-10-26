"""Paths, runtime settings and static reference data.

Policy thresholds and severities live in `policy_constants.py`; this module holds everything else
that is configuration rather than policy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
POLICY_DIR = DATA_DIR / "policy-docs"
RECEIPTS_PATH = DATA_DIR / "receipts.jsonl"
TAXONOMY_PATH = DATA_DIR / "category-taxonomy.md"
CACHE_DIR = ROOT / "cache"
OUTPUTS_DIR = ROOT / "outputs"
FIXTURES_DIR = ROOT / "tests" / "fixtures"

# Receipts that depend on the optional transaction-pattern rules (TIME-01..TIME-04). They are
# processed but excluded from every metric (ADR-013).
OUT_OF_SCOPE_RECEIPTS = frozenset({"RCP-020", "RCP-021", "RCP-029", "RCP-030"})

# Home currency per employee country, used to tell domestic from international travel (MEAL-01).
# An unknown country raises a review signal instead of a guess (ADR-025).
COUNTRY_CURRENCY = {
    "US": "USD",
    "IN": "INR",
    "JP": "JPY",
    "SG": "SGD",
    "GB": "GBP",
    "DE": "EUR",
    "FR": "EUR",
    "NL": "EUR",
    "IE": "EUR",
    "PT": "EUR",
    "ES": "EUR",
}

# Approval reference prefix -> reference type (EXC-02, ADR-017). The data dictionary states every
# reference in the dataset is a pre-approval written `PA-<year>-<number>`. No other prefix is
# documented, so no other type is recognised: an unknown prefix satisfies no rule.
APPROVAL_REF_PREFIXES = {"PA-": "pre_approval"}


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    temperature: float
    confidence_threshold: float
    budget_usd: float


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        api_key=os.getenv("OPENROUTER_API_KEY") or None,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=os.getenv("LLM_MODEL", "anthropic/claude-haiku-4.5"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.5")),
        budget_usd=float(os.getenv("LLM_BUDGET_USD", "2.0")),
    )

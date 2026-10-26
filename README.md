# Expense Policy Validator

Reads itemized expense receipts, classifies every line item into a spend category, checks each
receipt against written expense policies with a **deterministic policy engine**, and reports
evidence-grounded exceptions with a final disposition of `flag`, `review` or `pass`.

```
Receipt → Normalise → Classify items → Retrieve rules → Apply rules → Report exceptions
```

> Status: **repository setup.** The pipeline is not implemented yet — sections marked _TODO_ are
> filled in as the work progresses. The full brief is in [`docs/brief.html`](docs/brief.html).

## Project structure

```
.
├── app/
│   └── viewer.py              # Streamlit viewer: receipt list, detail, metrics
├── data/
│   ├── README.md              # Data dictionary — read first
│   ├── category-taxonomy.md   # 21 categories, restricted yes/no
│   ├── policy-docs/           # 9 policy documents, 41 rules (ALC-01, TECH-02, …)
│   └── receipts.jsonl         # 32 receipts / 79 line items, with labels (evaluation only)
├── docs/
│   ├── brief.html             # Original project brief
│   └── aws-design.md          # Part 4 — one-page AWS deployment design
├── outputs/                   # Committed per-receipt results (JSONL) and metrics
├── src/policy_validator/
│   ├── normaliser.py          # 1. Clean and translate line-item text
│   ├── classifier.py          # 2. Category + restricted flag + confidence (LLM)
│   ├── retriever.py           # 3. Find candidate rules (no vector DB)
│   ├── engine.py              # 4. Deterministic rules + EXC-01 disposition (no LLM)
│   ├── reporter.py            # 5. Reviewer-readable findings citing policy text
│   ├── baseline.py            # Keyword baseline for comparison
│   └── evaluate.py            # Metrics on the 28 in-scope receipts
├── tests/                     # Policy engine unit tests
├── .env.example               # Environment variable template
├── main.py                    # Entry point
└── pyproject.toml / uv.lock   # Dependencies (managed with uv)
```

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create .venv and install dependencies
cp .env.example .env         # then put your real OPENROUTER_API_KEY in .env
```

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | — | OpenRouter key (OpenAI-compatible). **Never commit it.** |
| `OPENROUTER_BASE_URL` | no | `https://openrouter.ai/api/v1` | API endpoint |
| `LLM_MODEL` | no | `anthropic/claude-haiku-4.5` | Model for normalisation/classification |
| `LLM_TEMPERATURE` | no | `0` | Kept at 0 for reproducibility |
| `CONFIDENCE_THRESHOLD` | no | `0.6` | Below this, raise an EXC-03 review signal |

## Usage

_TODO_ — commands to run the pipeline, the tests and the viewer:

```bash
uv run python main.py                       # run the pipeline → outputs/results.jsonl
uv run pytest                               # policy engine unit tests
uv run streamlit run app/viewer.py          # viewer
```

## Scope

Every rule except the transaction-pattern rules **TIME-01…TIME-04** is in scope. Receipts
RCP-020, RCP-021, RCP-029 and RCP-030 are out of scope, leaving **28 scored receipts**
(9 pass, 16 flag, 3 review; 65 line items).

Labels (`labels`, `line_items[].labels`, `notes`) are used **only for evaluation** — never as
input to the system or inside a prompt.

## Architecture

_TODO_ — the five components, how data flows between them, and caching of model calls.

## Prompts

_TODO_ — the main prompts and why they are written that way.

## Policy engine

_TODO_ — how rules are encoded (thresholds in USD, carve-outs requiring evidence, regional
overrides from `regional-addendum.md`, EXC-01 disposition) and the chosen confidence threshold.

## Evaluation summary

_TODO_ — on the 28 in-scope receipts:

- Classification: macro F1 across categories, F1 on `restricted = true`
- Disposition 3×3 confusion matrix
- False positives (of 9 pass) and missed violations (of 16 flag)
- Keyword baseline comparison
- Two failure cases and the stage that caused them
- The base-rate question

## Walkthrough: one receipt end to end

_TODO_

## AI collaboration

_TODO_ — assistants used and for what, at least one thing an assistant got wrong and how it was
caught, and what was checked by hand.

## Data handling

_TODO_ — which services received receipt or policy data (coding assistants, OpenRouter, …).

## Spend

_TODO_ — model chosen and why, and approximate spend (should match the OpenRouter dashboard).

## What I would do next

_TODO_

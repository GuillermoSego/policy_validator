# Expense Policy Validator

Classifies every line item on an expense receipt, checks the receipt against nine written policies
with a **deterministic rule engine**, and reports evidence-grounded exceptions with a disposition of
`flag`, `review` or `pass`. Design decisions: [`docs/ADRs.md`](docs/ADRs.md) (38 ADRs). Brief:
[`docs/brief.html`](docs/brief.html).

**Result on the 28 scored receipts:** category macro F1 **1.000**, restricted F1 **1.000**,
dispositions **28/28**, 0 false positives, 0 missed violations, for **$0.10** of model spend.
On 28 receipts that is a weak claim: see [evaluation](docs/evaluation.md#7-the-base-rate-question).

## Setup and usage

```bash
uv sync                      # Python ≥3.10, https://docs.astral.sh/uv/
cp .env.example .env         # set OPENROUTER_API_KEY (only needed for new model calls)
make test                    # 139 tests: engine, registry, LLM client, replay, metrics, viewer
make run                     # pipeline -> outputs/results.jsonl (replays the committed cache: $0)
make oracle baseline         # ablation + keyword baseline
make evaluate                # -> outputs/metrics.json, outputs/metrics.md
make viewer                  # Streamlit viewer: uv run streamlit run app/viewer.py
```

Environment: `OPENROUTER_API_KEY` (required for uncached calls), `LLM_MODEL`
(`anthropic/claude-haiku-4.5`), `LLM_TEMPERATURE` (`0`), `CONFIDENCE_THRESHOLD` (`0.5`),
`LLM_BUDGET_USD` (`2.0`), `OPENROUTER_BASE_URL`. Every model response is in the committed `cache/`,
so the whole pipeline re-runs offline and CI runs it with no secret (ADR-007, ADR-038).

## Architecture

```
receipts.jsonl ─(labels stripped)─► 1 Normaliser ─► 2 Classifier ─► 3 Retriever ─► 4 Engine ─► 5 Reporter ─► results.jsonl
                                    LLM, non-en only  LLM, 1 call/receipt  deterministic   deterministic   rule text as evidence
```

`src/policy_validator/`: **normaliser** (Unicode cleanup; translates non-English lines in one call
per receipt), **classifier** (category, confidence and item *facts* — gift, recipient and recipient
type, prescription, mobile handset, entertainment venue; `restricted` comes from the taxonomy, not
the model), **retriever** (deterministic triggers on categories, facts, MCC, declared type, entity
and currency; recall-oriented; the engine evaluates only what it returns), **engine** (rules as pure
functions), **reporter** (rule ID, policy doc, severity, cited lines, policy text, explanation with the
numbers). `llm.py` adds the SHA-256 response cache, two retries and a hard budget cap. The model
reads text; code makes every decision (ADR-014).

## Prompts

In [`prompts.py`](src/policy_validator/prompts.py), versioned (the version is in the cache key and on
every result). **Normaliser:** translate faithfully and keep product names, sizes and quantities —
never classify, so a wrong category can be attributed to translation *or* classification. The
**classifier** gets the taxonomy with its examples, the policy's own identification rule ("by the
nature of the item, not the words in its name", with the policy's examples), a warning that the
declared expense type may be wrong, strict definitions of each fact, and a confidence rubric. It
sees the English text, the original text and the receipt context, and it never decides
allowability. Output is constrained by a JSON schema with the category as an enum and validated with
Pydantic. Zero-shot: no dataset item is in any prompt (ADR-021, ADR-036).

## Policy engine

[`engine.py`](src/policy_validator/engine.py): each rule is a function registered under its ID that
returns a hit or nothing. Thresholds and severities are in
[`policy_constants.py`](src/policy_validator/policy_constants.py), and a test checks each one appears
in the policy text. **Thresholds** are compared in USD at cent precision ("above" is strict, "or
more" is inclusive). **Carve-outs** need the right *kind* of reference (EXC-02): `PA-` is a
pre-approval and waives only TECH-02. **Regional overrides:** REG-01 replaces ALC-01/02/03 for APAC,
and REG-02/REG-03 replace MEAL-01. **Cross-receipt rules** use batch aggregates (meal cap per
employee per day, OTC per trip). **Disposition** is EXC-01 exactly. **Confidence threshold: 0.5.**
Items below it raise one EXC-03 signal and are excluded from every other rule. In this data every
item scored ≥ 0.90, so the threshold never fires (ADR-037). Unit tests cover the brief's five cases
plus boundaries; the oracle (gold categories → same engine) matches all 28 answers exactly.

## Evaluation summary

| 28 receipts | Pipeline | Keyword baseline + same engine | Legacy keyword flagging |
|---|---|---|---|
| Category macro F1 / restricted F1 | 1.000 / 1.000 | 0.869 / 0.780 | — |
| Disposition accuracy | 28/28 | 24/28 | 18/28 |
| False positives (of 9) / missed (of 16) | 0 / 0 | 2 / 1 | 2 / 5 |

Confusion matrices, per-rule precision/recall, evidence accuracy (100% exact `line_ids`), retriever
recall (100%) and threshold sensitivity are in [`outputs/metrics.md`](outputs/metrics.md). The
keyword baseline fails on other languages and on misleading names. Most of its remaining value comes
from the engine: without one, accuracy falls to 64%. Both failure cases are out-of-scope TIME-rule
receipts (RCP-021: MEAL-01 raised instead of TIME-03; RCP-030: missed TIME-02 review). The full
write-up, including the base-rate question and caveats on the perfect score, is in
[`docs/evaluation.md`](docs/evaluation.md). AWS design: [`docs/aws-design.md`](docs/aws-design.md).

## One receipt end to end — RCP-025 (German, EMEA)

1. **Normaliser:** `Weisswein 0,2l` → "White wine 0,2l", `Schweinebraten mit Knoedel` → "Pork roast
   with dumplings" (one call; English receipts make none).
2. **Classifier:** L2 `alcohol` (0.98), L1 and L3 `food_beverage` (0.95).
3. **Retriever:** documentation and MCC rules, the meal rules (MEAL-01/02 plus REG-03 as the EMEA
   override), ALC-01/02/03 (alcohol present), DOC-04 and REG-04 (EUR, EMEA).
4. **Engine:** MCC 5812 is on-premise, so the alcohol rules apply. The receipt is declared *Meals -
   Individual* with no attendee count, so **ALC-01 (high)** fires on L2. REG-03: $37.80 per person
   is under EUR 70 × 1.08 = $75.60. REG-04: EUR 35 is not above EUR 50.
5. **Reporter:** ALC-01 cites `RCP-025-L2`, `meals-and-entertainment-policy.md` and the rule text;
   high severity → **flag**. This matches the correct answer.

## AI collaboration

I used **Claude Code** (Claude Opus 5.5) for the whole build: it interviewed me in three rounds of
design questions before writing code (the 30 initial ADRs are my answers), then implemented
milestone by milestone with tests. Things the assistant got wrong and how they were caught:

- **Leakage:** its first classifier prompt included "cooking wine" and "tablet case" as examples,
  near-verbatim dataset items. It caught them in a self-review of the prompt before the first paid
  call and removed them (ADR-036). The lesson: review prompts against the data, not only the code.
- **Wrong number in the docs:** the evaluation write-up first said "17 gold categories". A
  cross-check of every quoted figure against `metrics.json` showed 19.
- **Committed a lint failure** in the engine (an unused loop variable). Ruff caught it and a `[fix]`
  commit followed. A swallowed-error bug was also fixed before commit: an offline cache miss would
  have silently fallen back to the untranslated text, so `CacheMiss` was made a separate error type.

Checked by hand: <!-- YOU: list what you personally verified, e.g. reading every rule against the
engine, the RCP-016/RCP-022 outputs, the AWS numbers --> · Where I overruled the assistant:
<!-- YOU -->

**Data sent to services:** receipts and policies went to **Anthropic** (via Claude Code, during
development) and to **OpenRouter**, which routes to **Anthropic** (Haiku 4.5) for classification.
No other service received the data.

## Spend

Model: **`anthropic/claude-haiku-4.5`** at temperature 0, at $1/M input and $5/M output tokens.
Multilingual text and misleading names need language understanding, not long reasoning, and the
price allows many runs under the cap. Total spend: **$0.1025** (37 calls, 62.8k input / 7.9k output
tokens; [`run_manifest.json`](outputs/run_manifest.json)). This matches the key's usage delta on the
OpenRouter dashboard ($0.0780 → $0.1804).

## What I would do next

1. Implement TIME-01…TIME-04, which fixes both failure cases (ADR-032).
2. Replace self-reported confidence with agreement between two models or prompts, so EXC-03 means
   something (ADR-037).
3. Run a prompt ablation without the policy's examples, and a second model, to test how well the
   classifier generalises beyond this dataset.
4. Measure precision on a large sample at the real base rate before any production use.

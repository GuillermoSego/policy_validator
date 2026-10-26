# Expense Policy Validator

Classifies every line item on an expense receipt, checks the receipt against nine written policies
with a **deterministic rule engine**, and reports evidence-grounded exceptions with a disposition of
`flag`, `review` or `pass`. Design decisions: [`docs/ADRs.md`](docs/ADRs.md) (43 ADRs). Brief:
[`docs/brief.html`](docs/brief.html).

**Result on the 28 scored receipts:** category macro F1 **1.000**, restricted F1 **1.000**,
dispositions **28/28**, 0 false positives, 0 missed violations, for **$0.10** of model spend.
**Stretch:** TIME-01…TIME-03 are implemented, and all **32/32** receipts are right, including the
four timing receipts.

**Robustness checks:**
- Removing the policy's examples from the prompt gives the same 32/32.
- A second model (Gemini 2.5 Flash) gives the same 32/32 and agrees with Haiku on every category.

On this little data even that is a weak claim: see
[evaluation](docs/evaluation.md#7-the-base-rate-question).

## Setup and usage

```bash
uv sync                      # Python ≥3.10, https://docs.astral.sh/uv/
cp .env.example .env         # set OPENROUTER_API_KEY (only needed for new model calls)
make test                    # 183 tests: engine, TIME rules, registry, LLM, replay, metrics, viewer, demo
make run                     # pipeline -> outputs/results.jsonl (replays the committed cache: $0)
make oracle baseline         # oracle ablation + keyword baseline
make ablation                # prompt ablation without the policy's examples (replays cache)
make crossmodel              # Gemini 2.5 Flash run + two-model agreement (replays cache)
make evaluate                # -> outputs/metrics.json, outputs/metrics.md
make viewer                  # Streamlit viewer: uv run streamlit run app/viewer.py
make demo                    # live demo in the terminal, offline: see docs/demo.md
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

The modules in `src/policy_validator/`:
- **normaliser:** Unicode cleanup; translates non-English lines.
- **classifier:** category, confidence and item *facts* (gift, recipient type, prescription, handset,
  venue). `restricted` comes from the taxonomy.
- **retriever:** deterministic, recall-oriented triggers.
- **engine:** rules as pure functions.
- **reporter:** rule, policy doc, severity, cited lines, policy text, and an explanation with the
  numbers.

`llm.py` adds the response cache, retries and a hard budget cap. The model reads text; code makes
every decision (ADR-014).

## Prompts

In [`prompts.py`](src/policy_validator/prompts.py), versioned (the version is part of the cache key).

- **Normaliser:** translates faithfully and never classifies, so an error can be attributed to
  translation *or* classification.
- **Classifier:** receives the taxonomy, the policy's identification rule ("by the nature of the
  item, not the words in its name"), a warning that the declared type may be wrong, fact
  definitions and a confidence rubric. It sees the original and English text plus the receipt
  context, and never decides allowability.

Outputs are schema-constrained (category enum) and validated with Pydantic. No dataset item is in
any prompt (ADR-021, ADR-036). Removing the policy's examples leaves the result unchanged (ADR-042).

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
item scored ≥ 0.85, so the threshold never fires (ADR-037). Two-model disagreement, measured as
the alternative, also finds no uncertain item (ADR-043). The EXC-03 path is covered by tests. Unit
tests cover the brief's five cases plus boundaries and the TIME rules. The oracle (gold categories
→ same engine) matches all 32 answers exactly.

## Evaluation summary

| 28 receipts | Pipeline | Keyword baseline + same engine | Legacy keyword flagging |
|---|---|---|---|
| Category macro F1 / restricted F1 | 1.000 / 1.000 | 0.869 / 0.780 | — |
| Disposition accuracy | 28/28 | 24/28 | 18/28 |
| False positives (of 9) / missed (of 16) | 0 / 0 | 2 / 1 | 2 / 5 |

Evidence is exact on 100% of matched exceptions, and retriever recall is 100%. The keyword
baseline fails on other languages and on misleading names; without the engine it falls to 64%. The
two failure cases are v1 errors on the timing receipts (RCP-021, RCP-030), fixed by the TIME rules
(ADR-039). All tables are in [`outputs/metrics.md`](outputs/metrics.md); the write-up is in
[`docs/evaluation.md`](docs/evaluation.md). AWS design: [`docs/aws-design.md`](docs/aws-design.md).

## One receipt end to end — RCP-025 (German, EMEA)

1. **Normaliser:** `Weisswein 0,2l` → "White wine 0,2l", `Schweinebraten mit Knoedel` → "Pork roast
   with dumplings" (one call; English receipts make none).
2. **Classifier:** L2 `alcohol` (0.98), L1 and L3 `food_beverage` (0.95).
3. **Retriever:** documentation and MCC rules, the meal rules (MEAL-01/02 plus REG-03 as the EMEA
   override), ALC-01/02/03 (alcohol present), DOC-04 and REG-04 (EUR, EMEA), and TIME-01/02/03
   (timing, individual meal, splits).
4. **Engine:** MCC 5812 is on-premise, so the alcohol rules apply. The receipt is declared *Meals -
   Individual* with no attendee count, so **ALC-01 (high)** fires on L2. REG-03: $37.80 per person
   is under EUR 70 × 1.08 = $75.60. REG-04: EUR 35 is not above EUR 50.
5. **Reporter:** ALC-01 cites `RCP-025-L2`, `meals-and-entertainment-policy.md` and the rule text;
   high severity → **flag**. This matches the correct answer.

## AI collaboration

I used **Claude Code** (Claude Opus 5.5) throughout. It first put three rounds of design questions
to me; I reviewed and accepted its recommendations (the 30 initial ADRs). The later scope
decisions were mine: TIME rules, prompt ablation, second model, closing the project. It
implemented milestone by milestone, with tests.

What it got wrong, and how it was caught:
- **Leakage:** two prompt examples ("cooking wine", "tablet case") were near-verbatim dataset
  items. A review of the prompt against the data removed them before any paid call (ADR-036).
- **A wrong figure:** "17 gold categories" in the docs was really 19, found by cross-checking every
  number against `metrics.json`.
- **A committed lint failure:** caught by ruff and fixed in a `[fix]` commit.
- **A swallowed `CacheMiss`:** it would have hidden offline replay gaps; split from retryable errors.
- **An edit that silently did not apply:** it dropped two systems from the evaluation, and was
  spotted because the summary printed four systems instead of six.

Checked directly, not taken on trust:
- The oracle matches all 32 answers.
- Every figure in the docs matches `metrics.json`.
- The v1 failures were confirmed in git history.
- Spend matches the key's usage counter.
- A fresh clone with no key reproduces every output byte for byte.

**Data sent to services:** receipts and policies went to **Anthropic** (via Claude Code, during
development) and to **OpenRouter**, which routed them to **Anthropic** (Haiku 4.5, the pipeline and
the ablation) and **Google** (Gemini 2.5 Flash, the second-model check). No other service received
the data.

## Spend

Model: **`anthropic/claude-haiku-4.5`** at temperature 0, at $1/M input and $5/M output tokens.
Multilingual text and misleading names need language understanding, not long reasoning, and the
price allows many runs under the cap. Gemini 2.5 Flash, used only for the cross-model check, scored
the same. Production stays on one model because a second doubles calls with no measured gain.

**Total spend: $0.2224**:
- Pipeline: $0.1025 (37 calls, 62.8k input / 7.9k output tokens;
  [`run_manifest.json`](outputs/run_manifest.json)).
- Prompt ablation: $0.0939.
- Second model: $0.0260.

This equals the sum of the 105 cached responses and the key's usage delta on the OpenRouter
dashboard ($0.0780 → $0.3004).

## Scope and limitations

- **TIME-04 is not implemented:** the input has no trip dates (ADR-040).
- **The baggage-delay carve-out** cannot tell essential toiletries from other personal care
  (ADR-034). It is dormant on this data, which has no baggage-delay references.
- **EXC-03 is never triggered by the data:** neither self-reported confidence nor two-model
  agreement found an uncertain item (ADR-037, ADR-043).
- **All quality figures come from 32 receipts and 79 items.** What they can and cannot support is
  discussed in the [base-rate section](docs/evaluation.md#7-the-base-rate-question).

# Architecture Decision Records

Every non-trivial decision taken on this project is recorded here. Each entry has a status
(`Accepted`, `Superseded by ADR-NNN`, `Deprecated`), the context that forced the decision, the
decision itself, the alternatives considered, and its consequences. New decisions are appended;
existing entries are never rewritten — a changed decision gets a new ADR that supersedes the old one.

## Index

| ADR | Title | Status |
|---|---|---|
| [001](#adr-001--openai-sdk-against-openrouter) | `openai` SDK against OpenRouter | Accepted |
| [002](#adr-002--model-claude-haiku-45-at-temperature-0) | Model: Claude Haiku 4.5 at temperature 0 | Accepted |
| [003](#adr-003--normaliser-and-classifier-are-separate-llm-stages) | Normaliser and classifier are separate LLM stages | Accepted |
| [004](#adr-004--self-reported-confidence-exc-03-threshold-05) | Self-reported confidence, EXC-03 threshold 0.5 | Accepted |
| [005](#adr-005--deterministic-rule-retriever) | Deterministic rule retriever | Accepted |
| [006](#adr-006--rules-as-registered-python-functions) | Rules as registered Python functions | Accepted |
| [007](#adr-007--committed-on-disk-llm-cache) | Committed on-disk LLM cache | Accepted |
| [008](#adr-008--pydantic-v2-for-all-data-boundaries) | Pydantic v2 for all data boundaries | Accepted |
| [009](#adr-009--argparse-cli-and-makefile) | argparse CLI and Makefile | Accepted |
| [010](#adr-010--ruff-pytest-and-github-actions) | ruff, pytest and GitHub Actions | Accepted |
| [011](#adr-011--dependency-set) | Dependency set | Accepted |
| [012](#adr-012--streamlit-viewer-over-committed-outputs) | Streamlit viewer over committed outputs | Accepted |
| [013](#adr-013--time-01time-04-out-of-scope-for-v1) | TIME-01…TIME-04 out of scope for v1 | Accepted |
| [014](#adr-014--the-llm-extracts-facts-the-engine-decides) | The LLM extracts facts, the engine decides | Accepted |
| [015](#adr-015--restricted-is-derived-from-the-taxonomy) | `restricted` is derived from the taxonomy | Accepted |
| [016](#adr-016--batch-aggregates-for-cross-receipt-rules) | Batch aggregates for cross-receipt rules | Accepted |
| [017](#adr-017--approval-reference-type-parsed-from-its-prefix) | Approval reference type parsed from its prefix | Accepted |
| [018](#adr-018--missing-eur-rate-raises-a-review-signal) | Missing EUR rate raises a review signal | Accepted |
| [019](#adr-019--the-engine-evaluates-only-retrieved-rules) | The engine evaluates only retrieved rules | Accepted |
| [020](#adr-020--classifier-input-normalised-text-raw-text-and-receipt-context) | Classifier input: normalised text, raw text and receipt context | Accepted |
| [021](#adr-021--zero-shot-prompts-no-dataset-examples) | Zero-shot prompts, no dataset examples | Accepted |
| [022](#adr-022--keyword-baseline-feeds-the-same-engine) | Keyword baseline feeds the same engine | Accepted |
| [023](#adr-023--oracle-ablation-for-the-policy-engine) | Oracle ablation for the policy engine | Accepted |
| [024](#adr-024--engine-tests-use-hand-written-fixtures) | Engine tests use hand-written fixtures | Accepted |
| [025](#adr-025--country-to-currency-map-in-configuration) | Country-to-currency map in configuration | Accepted |
| [026](#adr-026--llm-failure-handling) | LLM failure handling | Accepted |
| [027](#adr-027--hard-budget-cap-in-code) | Hard budget cap in code | Accepted |
| [028](#adr-028--english-lines-skip-the-translation-call) | English lines skip the translation call | Accepted |
| [029](#adr-029--rule-registry-parsed-from-the-policy-markdown) | Rule registry parsed from the policy markdown | Accepted |
| [030](#adr-030--aws-target-architecture) | AWS target architecture | Accepted |

---

## ADR-001 — `openai` SDK against OpenRouter

- **Status:** Accepted
- **Context:** Model access is through an OpenRouter key. OpenRouter exposes an
  OpenAI-compatible API at `https://openrouter.ai/api/v1`.
- **Decision:** Use the official `openai` Python SDK with `base_url` set to OpenRouter.
- **Alternatives considered:** raw `httpx` (more code for retries and parsing); LiteLLM (a large
  dependency for a single provider).
- **Consequences:** One small, well-known dependency. Switching provider is a config change.

## ADR-002 — Model: Claude Haiku 4.5 at temperature 0

- **Status:** Accepted
- **Context:** The budget is capped (the brief says $5). The task needs multilingual
  understanding and resistance to misleading names ("beer-battered cod", "Arnold Palmer"), not
  long reasoning.
- **Decision:** `anthropic/claude-haiku-4.5`, `temperature=0`. The model ID is recorded on every
  result row. Price is checked on OpenRouter before the first paid run.
- **Alternatives considered:** `google/gemini-2.5-flash`, `openai/gpt-4o-mini` (cheaper, comparable);
  Sonnet-class models (several times the cost per run for a task that does not need them).
- **Consequences:** A full run costs cents, so many runs fit in the budget. Temperature 0 reduces
  but does not eliminate non-determinism; the cache (ADR-007) makes re-runs exact.

## ADR-003 — Normaliser and classifier are separate LLM stages

- **Status:** Accepted
- **Context:** The brief requires the five components to be kept separate and asks, for each failure,
  which stage caused it (translation, classification, retrieval, rule logic).
- **Decision:** Two separate LLM calls per receipt: the normaliser translates non-English lines; the
  classifier then categorises all lines. Both outputs are stored.
- **Alternatives considered:** one call that translates and classifies (cheaper, but a wrong
  category could not be attributed to translation vs classification).
- **Consequences:** Failure attribution is evidence-based: the stored translation shows whether the
  meaning survived. Marginal extra cost (only non-English receipts need the first call, ADR-028).

## ADR-004 — Self-reported confidence, EXC-03 threshold 0.5

- **Status:** Accepted
- **Context:** EXC-03 needs a per-item confidence. Logprobs are not reliably exposed for Claude
  models through OpenRouter; self-consistency sampling multiplies cost.
- **Decision:** The classifier reports a confidence in [0, 1] guided by an explicit rubric in the
  prompt. Items below **0.5** raise an `EXC-03` review signal and are excluded from every other rule.
  The threshold was fixed before seeing any results; a sensitivity table at 0.4 / 0.6 / 0.7 is
  reported in the evaluation.
- **Alternatives considered:** logprobs (unavailable); N-sample agreement (N× cost); tuning the
  threshold on the labelled data (would overfit 65 items and inflate the reported numbers).
- **Consequences:** Self-reported confidence is poorly calibrated in general; the sensitivity table
  makes that visible instead of hiding it. Every EXC-03 signal counts as unmatched by design.

## ADR-005 — Deterministic rule retriever

- **Status:** Accepted
- **Context:** The corpus is nine short documents (~3,700 words) and 41 rules. The brief forbids a
  vector database.
- **Decision:** The retriever selects candidate rules from a rule registry (ADR-029) using
  deterministic triggers: item categories and attributes, MCC, entity, declared expense type,
  currency, itemization and totals. It returns rule objects whose text is later cited as evidence.
- **Alternatives considered:** BM25 / keyword search over paragraphs; an in-memory embedding index.
  Both add fuzziness and cost without improving recall on a corpus this small.
- **Consequences:** Retrieval is explainable ("TECH-02 retrieved because item L2 is
  `computer_accessory`") and testable. Its recall is measured against the gold rule IDs (ADR-019).

## ADR-006 — Rules as registered Python functions

- **Status:** Accepted
- **Context:** The policy engine must be deterministic code. Rules mix thresholds, evidence-gated
  carve-outs, regional overrides and cross-receipt aggregates.
- **Decision:** Each rule is a pure function `(ReceiptContext) -> RuleOutcome | None`, registered with
  a decorator carrying its metadata (rule ID, policy doc, scope: whole-receipt or line-level).
  Thresholds and severities live in `policy_constants.py`, each citing its policy source.
- **Alternatives considered:** declarative YAML rules with an interpreter — regional overrides and
  carve-outs would end up as code embedded in YAML.
- **Consequences:** Every rule is unit-testable in isolation and readable in a code review.

## ADR-007 — Committed on-disk LLM cache

- **Status:** Accepted
- **Context:** The brief asks to classify each item once and re-run evaluation for free. Reviewers
  should be able to reproduce results without a key.
- **Decision:** Every LLM response is cached as a JSON file under `cache/`, keyed by
  `sha256(model, prompt_version, input)`, and the cache is **committed**. A cache hit never calls the
  network. Bumping a prompt version invalidates its entries naturally.
- **Alternatives considered:** a gitignored cache with only `outputs/` committed — evaluation would
  be reproducible, the pipeline would not.
- **Consequences:** `validator run` is fully reproducible offline, and CI runs it without secrets.
  The data is synthetic, so committing model responses carries no privacy risk.

## ADR-008 — Pydantic v2 for all data boundaries

- **Status:** Accepted
- **Context:** Data crosses three boundaries: the JSONL input, LLM responses, and the output file.
- **Decision:** Pydantic v2 models validate all three. An LLM response with a category outside the
  taxonomy fails validation and is retried (ADR-026).
- **Alternatives considered:** plain dicts / dataclasses with manual checks.
- **Consequences:** Malformed data fails loudly at the boundary instead of deep inside a rule.

## ADR-009 — argparse CLI and Makefile

- **Status:** Accepted
- **Decision:** A `validator` console script (`run`, `oracle`, `baseline`, `evaluate`) built with
  argparse; `main.py` is a thin wrapper; a Makefile gives one-word entry points.
- **Alternatives considered:** Typer / Click (extra dependency for four subcommands).
- **Consequences:** No extra dependency; standard library only.

## ADR-010 — ruff, pytest and GitHub Actions

- **Status:** Accepted
- **Decision:** ruff for lint and format, pytest for tests, and a GitHub Actions workflow that runs
  lint and tests on every push — without any secret, thanks to the committed cache.
- **Alternatives considered:** mypy and pre-commit hooks — useful, but not worth the time budget.
- **Consequences:** Every pushed commit is checked; no key is ever stored in CI.

## ADR-011 — Dependency set

- **Status:** Accepted
- **Decision:** Runtime: `openai`, `pydantic`, `python-dotenv`, `pandas`, `numpy`, `scikit-learn`
  (metrics), `streamlit`. Dev: `pytest`, `ruff`. `matplotlib` removed (the viewer uses Streamlit's
  own tables). The macro-F1 computation is cross-checked against a hand computation in a test,
  because the brief's definition (categories never predicted count as zero) is easy to get wrong.
- **Consequences:** Small, standard stack managed by `uv` with a committed lockfile.

## ADR-012 — Streamlit viewer over committed outputs

- **Status:** Accepted
- **Decision:** A Streamlit app with three views (receipt list, receipt detail, metrics) reading only
  `outputs/`. It never calls the model.
- **Consequences:** The demo works offline and instantly; what is shown is exactly what was evaluated.

## ADR-013 — TIME-01…TIME-04 out of scope for v1

- **Status:** Accepted
- **Context:** The brief makes the four transaction-pattern rules optional and excludes RCP-020,
  RCP-021, RCP-029 and RCP-030 from scoring.
- **Decision:** v1 does not implement them. The four receipts are still processed (classification
  and the other rules run) but excluded from the metrics.
- **Consequences:** Focus stays on the 28 scored receipts. The rules can be added later as
  deterministic engine functions without touching the LLM stages.

## ADR-014 — The LLM extracts facts, the engine decides

- **Status:** Accepted
- **Context:** Several rules need facts that the category alone does not carry: whether an item is a
  gift and who receives it (GIFT-01/03/04), prescription vs OTC (HEALTH-01), mobile handset
  (TECH-03), entertainment venue (ENT-01).
- **Decision:** The classifier returns, per item, `category`, `confidence` and a fixed `attributes`
  block: `is_gift`, `recipient`, `recipient_type` (`client`, `employee`, `government_official`,
  `self`, `unknown`), `is_prescription`, `is_mobile_handset`, `is_entertainment_venue`. The engine
  applies rules to these facts deterministically.
- **Alternatives considered:** keyword/regex extraction in the engine — exactly the brittle
  approach the project replaces, and it fails on six languages.
- **Consequences:** A clear line: the model reads text, the code makes decisions. An extraction error
  is attributable to the classifier stage.

## ADR-015 — `restricted` is derived from the taxonomy

- **Status:** Accepted
- **Decision:** The restricted flag is looked up from the category in `category-taxonomy.md`, not
  predicted separately.
- **Alternatives considered:** asking the model for both (they could contradict each other).
- **Consequences:** Category and flag are always consistent; restricted-F1 errors are purely
  category errors that cross the restricted boundary.

## ADR-016 — Batch aggregates for cross-receipt rules

- **Status:** Accepted
- **Context:** MEAL-01 / REG-02 / REG-03 sum one employee's meals per calendar date; HEALTH-01 caps OTC
  medication per trip; the PERS-01/02 baggage-delay allowance is shared per delay.
- **Decision:** The engine receives the whole batch and precomputes aggregates (per employee-date and
  per trip) before evaluating each receipt.
- **Alternatives considered:** strictly per-receipt evaluation — contradicts the policy text.
- **Consequences:** The engine's API is batch-level. In production this becomes state keyed by
  employee-date and trip (see ADR-030).

## ADR-017 — Approval reference type parsed from its prefix

- **Status:** Accepted
- **Context:** EXC-02: a reference satisfies a rule only if it is the kind that rule asks for
  (pre-approval for TECH-02, VP approval for ENT-01, manager approval for TECH-04, baggage-delay
  reference for PERS-01/02). Every reference in the dataset is `PA-…` (a pre-approval).
- **Decision:** A configured prefix map determines the reference type. `PA-` is a pre-approval and
  satisfies TECH-02 only. Unknown prefixes satisfy nothing.
- **Consequences:** e.g. RCP-016's `PA-2026-0398` does not waive REG-01; RCP-027 has no
  baggage-delay reference, so PERS-02 applies.

## ADR-018 — Missing EUR rate raises a review signal

- **Status:** Accepted
- **Context:** REG-03 and REG-04 convert a EUR amount at "the euro rate on the transaction date". For
  a non-EUR receipt from an EMEA employee that rate is not in the data. No such receipt exists in the
  dataset today.
- **Decision:** If the EUR rate is not available, the rule is not evaluated and a review signal with
  that rule ID is raised instead.
- **Alternatives considered:** a static reference-rate table (silently wrong on the actual date); raising
  an error (blocks the whole batch).
- **Consequences:** Conservative, consistent with EXC-03: a missed review costs less than a false
  accusation.

## ADR-019 — The engine evaluates only retrieved rules

- **Status:** Accepted
- **Decision:** The engine evaluates only the rules the retriever returns. The retriever is designed
  for recall (over-retrieval is cheap; the engine discards non-applicable rules). Retriever recall
  against the gold rule IDs is reported.
- **Alternatives considered:** the engine always evaluates every rule and the retriever only supplies
  citations — retrieval would then be decorative.
- **Consequences:** Retrieval is a real stage with a measurable failure mode.

## ADR-020 — Classifier input: normalised text, raw text and receipt context

- **Status:** Accepted
- **Decision:** For each item the classifier sees the normalised English text and the raw original,
  plus the receipt context: merchant, MCC and description, declared expense type, attendee count.
- **Consequences:** Nuance lost in translation is recoverable from the raw text; "context decides"
  cases (cooking wine at a supermarket) have the merchant available. The classifier still only says
  *what* an item is, never whether it is allowed.

## ADR-021 — Zero-shot prompts, no dataset examples

- **Status:** Accepted
- **Decision:** Prompts contain the full taxonomy with its examples and the policy's own
  identification principles ("classify by the nature of the item, not the words in its name"), but
  no items from the dataset. If quality is insufficient, invented few-shot examples may be added via a
  new ADR — never dataset items.
- **Consequences:** No label leakage; reported scores are an honest estimate.

## ADR-022 — Keyword baseline feeds the same engine

- **Status:** Accepted
- **Decision:** The baseline is a keyword → category dictionary (default category by declared
  expense type) feeding the **same** retriever and engine, so every metric compares like with like and
  isolates the classifier's contribution. A one-line "legacy" figure (flag whenever any restricted
  keyword appears) is also reported.
- **Consequences:** The comparison is fair and shows where keywords actually do fine.

## ADR-023 — Oracle ablation for the policy engine

- **Status:** Accepted
- **Decision:** An evaluation-only run feeds the gold categories (and gold-derived attributes) to the
  engine. It measures engine correctness independently of the classifier. It is never part of the
  pipeline and is labelled as an ablation everywhere it appears.
- **Consequences:** Failure attribution becomes objective: if the oracle run is right and the real
  run is wrong, the classifier (or normaliser) is at fault.

## ADR-024 — Engine tests use hand-written fixtures

- **Status:** Accepted
- **Decision:** Unit tests build receipts by hand mirroring the brief's five cases (RCP-027, RCP-016,
  RCP-006/RCP-026, RCP-031, RCP-028) plus boundary cases per rule, independent of `receipts.jsonl`
  and the LLM. An integration test runs the oracle over the 28 scored receipts.
- **Consequences:** Tests are fast, deterministic and run in CI without a key.

## ADR-025 — Country-to-currency map in configuration

- **Status:** Accepted
- **Context:** MEAL-01 calls travel international when the receipt currency differs from the home
  country's currency.
- **Decision:** A configured map for the dataset's countries (US, IN, JP, SG, GB, DE, FR, NL, IE, PT,
  ES). An unknown country raises a review signal instead of guessing.

## ADR-026 — LLM failure handling

- **Status:** Accepted
- **Decision:** Up to 2 retries with exponential backoff on network errors, malformed JSON or schema
  violations. If still failing, items get `category=other`, `confidence=0.0`, which raises EXC-03.
- **Consequences:** No receipt is dropped; a failure is visible to the reviewer instead of silently
  turning into a pass or an exception.

## ADR-027 — Hard budget cap in code

- **Status:** Accepted
- **Decision:** Each response's cost (OpenRouter `usage.cost`) is stored in the cache entry and
  accumulated; the run aborts once spend in the run exceeds **$2**.
- **Consequences:** A runaway loop cannot drain the key; reported spend is backed by data.

## ADR-028 — English lines skip the translation call

- **Status:** Accepted
- **Decision:** All lines get deterministic cleanup (whitespace, casing of units). Only receipts with
  non-English lines (per the input `language` field) call the LLM to translate, one call per receipt.
- **Consequences:** Fewer calls, and English text is never paraphrased by a model.

## ADR-029 — Rule registry parsed from the policy markdown

- **Status:** Accepted
- **Decision:** A parser extracts every rule (`**ID — Title.** text`) with its source document; that
  text is what exceptions cite as evidence. Severities and thresholds are encoded in code, and a test
  asserts each one appears verbatim in its rule's text, so a policy edit that changes a number breaks
  the build instead of silently diverging.
- **Consequences:** The policy documents remain the source of truth for citations without attempting
  to interpret rule logic from prose.

## ADR-030 — AWS target architecture

- **Status:** Accepted
- **Decision:** API Gateway (HTTP API) with a Cognito JWT authorizer; Lambda for the pipeline; policy
  documents in versioned S3, reloaded on change and recorded per decision; the OpenRouter key in
  Secrets Manager; DynamoDB for employee-date and trip aggregates (ADR-016); SQS with a DLQ to absorb
  spikes and model outages; CloudWatch for logs and metrics. Cost is estimated from tokens measured in
  our own runs. Details in [`aws-design.md`](aws-design.md).

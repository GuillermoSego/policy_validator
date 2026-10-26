# Evaluation

All numbers are on the **28 in-scope receipts** (65 line items; 9 pass, 16 flag, 3 review) and are
regenerated from committed files with `make evaluate`. Full tables, per-rule precision/recall and the
confusion matrices for every system are in [`outputs/metrics.md`](../outputs/metrics.md).

Three systems are compared:

- **Pipeline** — the real system: LLM normaliser + classifier, deterministic retriever and engine.
- **Keyword baseline** — an English keyword matcher feeding the *same* retriever and engine
  (ADR-022), so the difference isolates the classifier.
- **Oracle** — gold categories fed to the engine (ADR-023). An evaluation-only ablation: it measures
  the deterministic half on its own.

## 1. Classification

| | Pipeline | Keyword baseline |
|---|---|---|
| Category macro F1 (19 gold categories) | **1.000** | 0.869 |
| Category accuracy | 65/65 | 55/65 |
| Restricted F1 (restricted = positive) | **1.000** | 0.780 |

**What this says about the engine's inputs.** Restricted F1 tells whether the engine is told the
right thing about *allowability-relevant* items; macro F1 tells whether it gets the exact category
that rules like TECH-02, LAUNDRY-01, DOC-03 and the meal rules need. Both are perfect for the
pipeline, so on this dataset every engine decision rests on correct inputs — confirmed by the
oracle producing identical results. The baseline shows why both scores matter: its restricted F1
(0.78) is dragged down by alcohol it cannot see in other languages (Rioja, Weisswein) and alcohol it
invents from food names (beer-battered cod, rum cake, a non-alcoholic mojito); its category errors on
*unrestricted* items (dry cleaning → household goods because of the word "cleaning"; Portuguese
"limpeza a seco" → other) break LAUNDRY-01 even though no restricted item is involved.

## 2. Disposition — 3×3 confusion matrix (rows = correct, columns = predicted)

| Pipeline | flag | review | pass |
|---|---|---|---|
| **flag** | 16 | 0 | 0 |
| **review** | 0 | 3 | 0 |
| **pass** | 0 | 0 | 9 |

The keyword baseline gets 24/28 (85.7%): RCP-004 and RCP-009 pass→flag, RCP-025 flag→pass,
RCP-031 review→pass.

## 3. False positives and 4. missed violations

| | False positives (of 9 pass) | Missed violations (of 16 flag) |
|---|---|---|
| Pipeline | **0** | **0** |
| Keyword baseline + engine | 2 (RCP-004, RCP-009) | 1 (RCP-025) |
| Legacy keyword flagging, no engine | 2 (RCP-004, RCP-009) | 5 (RCP-011, RCP-015, RCP-023, RCP-025, RCP-026) |

Exception-level results for the pipeline: precision 100%, recall 100%, evidence exact on 100% of
matched exceptions (cited `line_ids` equal the answer's), review signals 100%/100%, retriever recall
100% of the rules in the answers.

## 5. Keyword baseline — honest comparison

Where the keyword approach **does as well or better**:

- It is free, instant and fully deterministic; the pipeline costs ~$0.10 per 32 receipts and
  depends on an external API.
- It is right on several "hard" items by luck of the word list: cooking wine (ALC-03) and the
  supermarket cleaning products, and its engine-backed version still gets 24/28 dispositions —
  most of the value on this dataset comes from the **rule engine**, not the classifier. The
  legacy system *without* an engine falls to 64% (18/28), missing five violations that depend on
  amounts, approvals, itemization and context (RCP-015, RCP-023, RCP-026), not keywords.

Where it fails: every language other than English, and every name that contains an alcohol word
without being alcohol — exactly the two failure modes the brief warns about.

## 6. Two failure cases

The current system makes no errors on any of the 32 receipts. The two failures below are real wrong
outputs from **v1**, which was committed before the TIME rules existed. Run `git show
0db6ecb:outputs/results.jsonl` to see them. They were fixed by implementing TIME-01…TIME-03
(ADR-039), and the oracle integration test now pins all 32 receipts.

**RCP-021 (and its pair RCP-020): wrong exception. Stage: rule logic (rule not implemented).**
Both receipts are from the same employee, at the same merchant, on the same day. Each is under the
$75 cap, but together they come to $145.50 per person. v1 correctly aggregated meals per employee
per day (ADR-016) and raised **MEAL-01** on both. The correct answer is **TIME-03** (split
transaction), which per its own text replaces the meal cap for the group. The disposition was right
(flag) but the cited rule was wrong. The fix: detect splits in the batch aggregates, raise TIME-03
on the contributing receipts and suppress the threshold rule it replaces (ADR-041). No model change
was needed, since classification was already correct.

**RCP-030: missed review. Stage: retrieval and rule logic (TIME-02 neither retrieved nor
implemented).** This is a solo travel meal with no trip record, on a Saturday. v1 passed it because
the receipt is otherwise clean. It was the riskier of the two failures, a silent pass, and it shows
the retriever's blind spot by design: a rule missing from its trigger tables can never fire, however
good the classifier is. The fix: a TIME-02 rule, plus a retrieval trigger on the individual travel
expense types. **Before** implementing it, I checked that no scored receipt is a trip-less
individual travel expense, so the fix could not create false positives on the 28 receipts.

**Stretch result:** pipeline and oracle both get all 32 receipts right; the keyword baseline gets
28/32 (87.5%). TIME-04 is not implemented because the data has no trip dates (ADR-040).

A latent weakness found while evaluating: **self-reported confidence carries no signal
here.** Every item scored 0.90–1.00 (50 of 65 at exactly 0.95), so the EXC-03 threshold changes
nothing anywhere between 0.4 and 0.7 (sensitivity table in `outputs/metrics.md`). The threshold of 0.5
(ADR-004) is therefore untested on this data; on real, messier receipts I would expect it to matter,
and I would replace self-reported confidence with agreement across two models or two prompts.

**On the perfect score.** The prompt contains the policy's own identification examples
(beer-battered fish, rum cake, virgin mojito, Arnold Palmer — from `meals-and-entertainment-policy.md`),
which appear almost verbatim in RCP-004. Using policy text is legitimate — a real deployment would do
the same — but it means RCP-004 tests instruction following more than generalisation. No dataset
item is in any prompt (ADR-021); two examples that were too close to dataset items ("cooking wine",
"tablet case") were removed before the first run.

## 7. The base-rate question

More than half of these receipts contain a violation; a real stream has a few percent. False
positives are measured here on only 9 clean receipts, so "0 of 9" is consistent with a true
false-positive rate as high as ~30% (rule of three: 3/9 at 95% confidence). At a 3% violation rate,
even a 5% false-positive rate means roughly 48 false alarms for every 30 real violations — most
flags would be wrong, and reviewers would learn to ignore them. Before trusting this in production I
would measure the false-positive rate (and per-rule precision) on a large, random sample of
ordinary receipts at the real base rate and in the real language mix, and track it continuously
after launch alongside a sample of passed receipts audited by hand to estimate missed violations.

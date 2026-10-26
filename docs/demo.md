# Live demo

A terminal demo for the review session. It runs **offline** from the committed cache: no API key,
no spend, and the same output every time. Only `custom` calls the model.

```bash
uv sync                                   # once
make demo                                 # guided tour, 8 scenes, Enter between scenes
uv run validator demo tour --scene 4      # one scene
uv run validator demo list                # every receipt on one line
uv run validator demo trace RCP-025       # one receipt through the five stages
uv run validator demo whatif RCP-010 --set attendee_count=2 --set "submitted_expense_type=Client Entertainment"
uv run validator demo rule TECH-02        # a rule's policy text
uv run validator demo custom              # demo/custom_receipt.json through the full pipeline (key)
make viewer                               # Streamlit viewer, for the receipt list and metrics
```

## The tour (about 8 minutes)

| Scene | Receipt | What it shows |
|---|---|---|
| 1 Names lie | RCP-004 | Keyword matching flags beer-battered cod, a virgin mojito and rum cake; the classifier does not. |
| 2 One receipt, five stages | RCP-025 | German text translated, classified, rules retrieved with reasons, ALC-01 decided by code, policy text cited. |
| 3 Context decides | RCP-010 | Same beer: ALC-01 on a solo meal, pass at client entertainment for two, REG-01 for an APAC employee. |
| 4 Thresholds and evidence | RCP-006, RCP-027 | $200.00 passes, $200.01 is TECH-02, a `PA-` reference waives it; a `PA-` reference does not waive PERS-02. |
| 5 Severity ladder | RCP-022, 031, 028, 002 | Critical, low, signal-only and clean receipts through EXC-01; a five-night trip clears LAUNDRY-01. |
| 6 Rules across receipts | RCP-020, RCP-021 | A split meal is TIME-03 on both; moving one receipt a day clears both. |
| 7 Unsure or wrong | RCP-010, RCP-004 | Confidence 0.30 turns ALC-01 into an EXC-03 review; a wrong category becomes a false accusation. |
| 8 Reproducible and measured | all | 37 calls, 37 from cache, $0 spent; 28/28 vs 24/28 (keyword + engine) vs 18/28 (legacy). |

## Answering "what if…?" on the spot

`whatif` edits one receipt, keeps each item's cached classification, and re-runs the retriever, the
engine and EXC-01 over the whole batch, so cross-receipt effects show up too. Lines can be written
short (`L2` is `<receipt>-L2`).

| Question | Command |
|---|---|
| What if it were a client dinner for two? | `whatif RCP-010 --set "submitted_expense_type=Client Entertainment" --set attendee_count=2` |
| What if the employee were in India? | `whatif RCP-002 --set employee_country=IN` (entity follows the country) |
| What if the monitor cost less? | `whatif RCP-026 --usd L1=199.99` |
| What if there were a pre-approval? | `whatif RCP-026 --set pre_approval_ref=PA-2026-0001` |
| What if the trip were longer? | `whatif RCP-031 --set trip_nights=4` |
| What if no attendee count were recorded? | `whatif RCP-007 --set attendee_count=null` |
| What if the receipt were not itemized? | `whatif RCP-007 --set itemized=false` |
| What if the model were unsure? | `whatif RCP-024 --confidence L1=0.4` |
| What if the model were wrong? | `whatif RCP-012 --category L1=computer_accessory` |
| What if the gift were for an official? | `whatif RCP-018 --fact L1.recipient_type=government_official` |
| What if it were bought at 2 a.m.? | `whatif RCP-001 --set transaction_datetime=2026-04-14T02:10:00` |

Add `--trace` to print the full five-stage trace of the original receipt first.

## A receipt nobody has seen

`demo/custom_receipt.json` is an invented receipt (bourbon-glazed salmon, a Shirley Temple, a glass
of Spanish house wine, tiramisu). Edit it, or copy it, and run
`uv run validator demo custom path/to/receipt.json`. It needs `OPENROUTER_API_KEY` in `.env` and costs
well under one cent. The answers are cached in `.demo_cache/` (gitignored), so **run it once before
the session**: it then replays offline, even without network.

## If something goes wrong

- No colours, or odd characters: set `NO_COLOR=1`, or use a terminal with UTF-8.
- `custom` says "not cached": the key is missing or the receipt was never run with it; use `trace`
  on a dataset receipt instead.
- Everything else needs no network. If the network drops, the demo still runs.

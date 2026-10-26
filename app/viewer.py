"""Streamlit viewer — receipt list, receipt detail and metrics (ADR-012).

Reads only committed files in `outputs/` and the dataset; it never calls a model.
Launch: `make viewer` (or `uv run streamlit run app/viewer.py`).
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from policy_validator.config import OUTPUTS_DIR
from policy_validator.data import load_gold, load_receipts
from policy_validator.reporter import read_results

SYSTEM_FILES = {
    "Pipeline (LLM)": "results.jsonl",
    "Prompt ablation (no examples)": "ablation_no_examples_results.jsonl",
    "Second model (Gemini Flash)": "second_model_results.jsonl",
    "Two-model agreement": "agreement_results.jsonl",
    "Keyword baseline": "baseline_results.jsonl",
    "Oracle ablation": "oracle_results.jsonl",
}
BADGE = {"flag": "🔴 flag", "review": "🟡 review", "pass": "🟢 pass"}

st.set_page_config(page_title="Expense Policy Validator", layout="wide")


@st.cache_data
def load(system_file: str):
    results = {r.receipt_id: r for r in read_results(OUTPUTS_DIR / system_file)}
    receipts = {r.receipt_id: r for r in load_receipts()}
    return results, receipts, load_gold()


@st.cache_data
def load_metrics() -> tuple[dict, str]:
    return (
        json.loads((OUTPUTS_DIR / "metrics.json").read_text()),
        (OUTPUTS_DIR / "metrics.md").read_text(),
    )


st.sidebar.title("Expense Policy Validator")
view = st.sidebar.radio("View", ["Receipt list", "Receipt detail", "Metrics"])
system = st.sidebar.selectbox("System", list(SYSTEM_FILES))
results, receipts, gold = load(SYSTEM_FILES[system])
manifest_path = OUTPUTS_DIR / "run_manifest.json"
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text())
    st.sidebar.caption(
        f"Model `{manifest['model']}` · EXC-03 threshold {manifest['confidence_threshold']} · "
        f"run cost ${manifest['cost_usd']:.3f}"
    )


def receipt_list() -> None:
    st.header("Receipts")
    only_mismatch = st.checkbox("Show mismatches only")
    show_oos = st.checkbox("Include out-of-scope receipts (TIME rules)", value=False)
    rows = []
    for rid, result in results.items():
        g = gold[rid]
        if not show_oos and not g.in_scope:
            continue
        mine = {e.rule_id for e in result.exceptions}
        expected = {e["rule_id"] for e in g.exceptions}
        match = result.disposition == g.disposition and mine == expected
        if only_mismatch and match:
            continue
        r = receipts[rid]
        rows.append(
            {
                "receipt": rid,
                "merchant": r.merchant_name,
                "declared type": r.submitted_expense_type,
                "total USD": r.total_amount_usd,
                "predicted": BADGE[result.disposition],
                "correct": BADGE[g.disposition],
                "match": "✅" if match else "❌",
                "exceptions": ", ".join(sorted(mine)) or "—",
                "expected": ", ".join(sorted(expected)) or "—",
                "in scope": g.in_scope,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        st.success("No mismatches.")
        return
    in_scope = df[df["in scope"]]
    st.caption(
        f"{(in_scope['match'] == '✅').sum()} / {len(in_scope)} in-scope receipts match the "
        "correct disposition and exception rules."
    )
    st.dataframe(
        df.style.apply(
            lambda row: ["background-color: #fde2e2" if row["match"] == "❌" else ""] * len(row),
            axis=1,
        ),
        hide_index=True,
        use_container_width=True,
    )


def receipt_detail() -> None:
    st.header("Receipt detail")
    rid = st.selectbox("Receipt", list(results))
    result, r, g = results[rid], receipts[rid], gold[rid]

    cols = st.columns(4)
    cols[0].metric("Predicted", result.disposition)
    cols[1].metric("Correct", g.disposition)
    cols[2].metric("Total (USD)", f"{r.total_amount_usd:,.2f}")
    cols[3].metric("Entity", f"{r.entity} ({r.employee_country})")
    st.write(
        f"**{r.merchant_name}** · MCC {r.mcc} {r.mcc_description} · declared "
        f"*{r.submitted_expense_type}* · {r.transaction_datetime} · {r.currency} "
        f"@ {r.fx_rate_to_usd} · attendees {r.attendee_count} · trip {r.trip_id} "
        f"({r.trip_nights} nights) · approval ref {r.pre_approval_ref} · itemized {r.itemized}"
    )
    if not g.in_scope:
        st.info("Out of scope: depends on the optional TIME rules (not scored).")

    st.subheader("Line items")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "line": i.line_id,
                    "original": i.description_raw,
                    "English": i.description_en,
                    "category": i.category,
                    "correct category": g.item_categories[i.line_id],
                    "restricted": i.restricted,
                    "confidence": i.confidence,
                    "USD": i.amount_usd,
                    "facts": ", ".join(
                        f"{k}={v}"
                        for k, v in i.attributes.model_dump().items()
                        if v not in (False, None, "unknown")
                    ),
                    "rationale": i.rationale,
                }
                for i in result.line_items
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Raised by the system")
        if not result.exceptions and not result.review_signals:
            st.write("Nothing raised.")
        for e in result.exceptions:
            with st.expander(
                f"{e.rule_id} · {e.severity} · {', '.join(e.line_ids) or 'whole receipt'}",
                expanded=True,
            ):
                st.write(e.explanation)
                st.caption(f"{e.policy_doc}: {e.evidence}")
        for s in result.review_signals:
            st.warning(f"Review signal {s.rule_id}: {s.reason}")
    with right:
        st.subheader("Correct answer")
        if not g.exceptions and not g.review_signals:
            st.write("Nothing expected.")
        for e in g.exceptions:
            st.write(
                f"**{e['rule_id']}** · {e['severity']} · "
                f"{', '.join(e['line_ids']) or 'whole receipt'} — {e['reason']}"
            )
        for s in g.review_signals:
            st.write(f"Signal **{s['rule_id']}** — {s['reason']}")
        st.caption(f"Notes: {g.notes}")

    with st.expander("Retrieved rules"):
        st.dataframe(
            pd.DataFrame([rr.model_dump() for rr in result.retrieved_rules]),
            hide_index=True,
            use_container_width=True,
        )


def metrics() -> None:
    st.header("Metrics — 28 in-scope receipts")
    report, markdown = load_metrics()
    keys = {
        "Pipeline (LLM)": "pipeline",
        "Keyword baseline": "baseline",
        "Oracle ablation": "oracle",
    }
    cols = st.columns(3)
    for col, (label, key) in zip(cols, keys.items(), strict=True):
        c, d = report[key]["classification"], report[key]["disposition"]
        col.subheader(label)
        col.metric("Category macro F1", f"{c['macro_f1']:.3f}")
        col.metric("Restricted F1", f"{c['restricted_f1']:.3f}")
        col.metric("Disposition accuracy", f"{d['accuracy']:.1%}")
        col.metric("False positives / 9", d["false_positives"]["count"])
        col.metric("Missed violations / 16", d["missed_violations"]["count"])
    st.divider()
    st.markdown(markdown.split("\n", 3)[3])  # drop the generated-file header


{"Receipt list": receipt_list, "Receipt detail": receipt_detail, "Metrics": metrics}[view]()

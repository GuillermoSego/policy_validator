"""Live demo for the review session: `validator demo <command>`.

- `tour`    a guided walk through what the system does, in eight short scenes.
- `list`    every receipt on one line, to pick one on the spot.
- `trace`   one receipt through the five stages, with the reason for each decision.
- `whatif`  change a receipt fact, an amount, a category or a confidence, and re-decide.
- `custom`  a receipt you write yourself, through the full pipeline (calls the model once).

Everything except `custom` runs offline from the committed cache: no API key, no spend, and the
same output every time. `whatif` reuses the cached classification of each item and re-runs only the
deterministic half (retriever, engine, EXC-01), which is exactly the part the experiments are about:
the model says what an item is, the code decides whether it is allowed (ADR-014).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from . import policy_constants as pc
from .baseline import classify_receipt as keyword_classify
from .baseline import legacy_disposition
from .classifier import classify_receipt
from .config import OUT_OF_SCOPE_RECEIPTS, ROOT, load_settings
from .data import GoldReceipt, is_restricted, load_gold, load_receipts, load_taxonomy
from .llm import LLMClient
from .models import ClassifiedItem, ItemAttributes, Receipt, ReceiptResult
from .normaliser import normalise_receipt
from .pipeline import PROMPT_VERSIONS, classify_all, decide_all
from .policy_registry import load_registry

# Responses for custom receipts are cached here (gitignored), so a custom receipt rehearsed once
# with the key replays offline during the session.
DEMO_CACHE_DIR = ROOT / ".demo_cache"
EXAMPLE_CUSTOM_RECEIPT = ROOT / "demo" / "custom_receipt.json"

ENTITY_BY_COUNTRY = {
    **dict.fromkeys(("IN", "JP", "SG"), "APAC"),
    **dict.fromkeys(("GB", "DE", "FR", "NL", "IE", "PT", "ES"), "EMEA"),
}


class DemoError(ValueError):
    """A bad demo argument (unknown receipt, line, field or value)."""


# --- Output helpers ------------------------------------------------------------------------------

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "cyan": "36"}
_DISPOSITION_COLOR = {"flag": "red", "review": "yellow", "pass": "green"}


def _color_on() -> bool:
    return sys.stdout.isatty() and not os.getenv("NO_COLOR")


def style(text: str, *names: str) -> str:
    if not _color_on() or not names:
        return text
    return f"\033[{';'.join(_CODES[n] for n in names)}m{text}\033[0m"


def badge(disposition: str) -> str:
    return style(f"{disposition.upper():<7}", "bold", _DISPOSITION_COLOR[disposition])


def _width() -> int:
    return min(shutil.get_terminal_size((100, 24)).columns, 110)


def say(text: str = "", indent: int = 0) -> None:
    """Print wrapped prose."""
    if not text:
        print()
        return
    pad = " " * indent
    print(textwrap.fill(text, _width(), initial_indent=pad, subsequent_indent=pad))


def heading(text: str) -> None:
    print()
    print(style(f"━━ {text} " + "━" * max(0, _width() - len(text) - 4), "bold", "cyan"))


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _short(line_id: str) -> str:
    return line_id.rsplit("-", 1)[-1]


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# --- The world: receipts, cached classification and the answer key -------------------------------


@dataclass
class World:
    receipts: dict[str, Receipt]
    classified: dict[str, list[ClassifiedItem]]
    gold: dict[str, GoldReceipt]
    threshold: float
    model: str
    llm_calls: int = 0
    cache_hits: int = 0
    cost_of_responses: float = 0.0
    spent_this_run: float = 0.0

    def receipt(self, rid: str) -> Receipt:
        rid = rid.upper()
        if rid not in self.receipts:
            raise DemoError(f"unknown receipt {rid!r}; try `validator demo list`")
        return self.receipts[rid]

    def decide(
        self,
        receipts: list[Receipt] | None = None,
        classified: dict[str, list[ClassifiedItem]] | None = None,
    ) -> dict[str, ReceiptResult]:
        """The deterministic half — retriever, engine, reporter — on the whole batch."""
        results = decide_all(
            receipts if receipts is not None else list(self.receipts.values()),
            classified if classified is not None else self.classified,
            self.threshold,
            run="demo",
            model_id=self.model,
            prompt_versions=PROMPT_VERSIONS,
        )
        return {r.receipt_id: r for r in results}


def load_world() -> World:
    """Classify every receipt from the committed cache. The key is dropped on purpose: the demo
    can never spend money or depend on the network."""
    settings = dataclasses.replace(load_settings(), api_key=None)
    llm = LLMClient(settings)
    receipts = load_receipts()
    classified = classify_all(receipts, llm)
    u = llm.usage
    return World(
        receipts={r.receipt_id: r for r in receipts},
        classified=classified,
        gold=load_gold(),
        threshold=settings.confidence_threshold,
        model=settings.model,
        llm_calls=u.calls,
        cache_hits=u.cache_hits,
        cost_of_responses=u.cost_usd,
        spent_this_run=u.new_cost_usd,
    )


# --- Formatting a decision -----------------------------------------------------------------------


def why(result: ReceiptResult) -> str:
    """EXC-01 in words: the disposition is computed from the most severe exception."""
    if result.exceptions:
        top = max(result.exceptions, key=lambda e: pc.SEVERITY_RANK[e.severity]).severity
        if top == "critical":
            return "a critical exception → flag, routed to Compliance (EXC-01)"
        if pc.SEVERITY_RANK[top] >= pc.SEVERITY_RANK["medium"]:
            return f"most severe exception is {top} → flag (EXC-01)"
        return "only low-severity exceptions → review, not flag (EXC-01)"
    if result.review_signals:
        return "review signals only, no exception → review (EXC-01)"
    return "no exception and no review signal → pass (EXC-01)"


def summary(result: ReceiptResult) -> str:
    parts = [
        f"{e.rule_id} {e.severity}"
        + (f" [{','.join(_short(i) for i in e.line_ids)}]" if e.line_ids else "")
        for e in result.exceptions
    ]
    parts += [f"{s.rule_id} signal" for s in result.review_signals]
    return " · ".join(parts) or "nothing raised"


def gold_summary(g: GoldReceipt) -> str:
    parts = [
        f"{e['rule_id']} {e['severity']}"
        + (f" [{','.join(_short(i) for i in e['line_ids'])}]" if e["line_ids"] else "")
        for e in g.exceptions
    ]
    parts += [f"{s['rule_id']} signal" for s in g.review_signals]
    return " · ".join(parts) or "nothing raised"


def matches_gold(result: ReceiptResult, g: GoldReceipt) -> bool:
    mine = {(e.rule_id, tuple(e.line_ids)) for e in result.exceptions}
    expected = {(e["rule_id"], tuple(e["line_ids"])) for e in g.exceptions}
    signals = {s.rule_id for s in result.review_signals}
    expected_signals = {s["rule_id"] for s in g.review_signals}
    return result.disposition == g.disposition and mine == expected and signals == expected_signals


def print_findings(result: ReceiptResult, indent: int = 3) -> None:
    pad = " " * indent
    for e in result.exceptions:
        cited = ", ".join(_short(i) for i in e.line_ids) or "whole receipt"
        mark = style("✖", "red")
        print(f"{pad}{mark} {style(e.rule_id, 'bold')} {e.severity:<8} [{cited}]")
        say(e.explanation, indent + 4)
    for s in result.review_signals:
        print(f"{pad}{style('⚑', 'yellow')} {style(s.rule_id, 'bold')} review signal")
        say(s.reason, indent + 4)
    if not result.exceptions and not result.review_signals:
        print(f"{pad}{style('✔', 'green')} nothing raised")


def receipt_header(r: Receipt) -> None:
    heading(f"{r.receipt_id} · {r.merchant_name} · {r.entity} ({r.employee_country})")
    fx = (
        "" if r.currency == "USD" else f" ({r.currency} {r.total_amount:,.2f} @ {r.fx_rate_to_usd})"
    )
    trip = f"{r.trip_id} ({r.trip_nights} nights)" if r.trip_id else "no trip"
    say(
        f"declared {style(r.submitted_expense_type, 'bold')} · MCC {r.mcc} {r.mcc_description} · "
        f"{money(r.total_amount_usd)}{fx} · {r.transaction_datetime} · attendees "
        f"{r.attendee_count if r.attendee_count is not None else '—'} · {trip} · approval ref "
        f"{r.pre_approval_ref or '—'} · {'itemized' if r.itemized else 'NOT itemized'}",
        1,
    )


def print_trace(
    r: Receipt,
    items: list[ClassifiedItem],
    result: ReceiptResult,
    gold: GoldReceipt | None = None,
    threshold: float = 0.5,
) -> None:
    """One receipt through the five stages."""
    receipt_header(r)
    language = {line.line_id: line.language for line in r.line_items}

    print(style("\n 1 NORMALISER", "bold") + style("   LLM, only for non-English lines", "dim"))
    foreign = [i for i in items if language[i.line_id] != "en"]
    for i in foreign:
        print(f"   {_short(i.line_id):<4}{language[i.line_id]}  {i.description_raw}")
        print(f"         → {style(i.description_en, 'bold')}")
    if not foreign:
        print("   all lines in English: no model call, text only cleaned")

    print(
        style("\n 2 CLASSIFIER", "bold")
        + style("   LLM: what each item is — never whether it is allowed", "dim")
    )
    for i in items:
        facts = ", ".join(
            f"{k}={v}"
            for k, v in i.attributes.model_dump().items()
            if v not in (False, None, "unknown", "self")
        )
        restricted = style("restricted", "red") if i.restricted else "          "
        conf = f"{i.confidence:.2f}"
        if i.confidence < threshold:
            conf = style(conf + " < threshold", "yellow")
        print(
            f"   {_short(i.line_id):<4}{_cut(i.description_en, 38):<39}{i.category:<22}"
            f"{restricted} {conf:>5}  {money(i.amount_usd):>9}"
        )
        if facts:
            print(style(f"         facts: {facts}", "dim"))

    print(
        style("\n 3 RETRIEVER", "bold")
        + style("   deterministic: the rules that could apply, and why", "dim")
    )
    by_reason: dict[str, list[str]] = {}
    for rule in result.retrieved_rules:
        by_reason.setdefault(rule.reason, []).append(rule.rule_id)
    for reason, rule_ids in by_reason.items():
        ids = " ".join(rule_ids)
        if len(ids) > 38:
            print(f"   {ids}")
            ids = ""
        print(f"   {ids:<39}{style('← ' + reason, 'dim')}")

    fired = {e.rule_id for e in result.exceptions} | {s.rule_id for s in result.review_signals}
    quiet = [rr.rule_id for rr in result.retrieved_rules if rr.rule_id not in fired]
    print(
        style("\n 4 ENGINE", "bold")
        + style(
            f"   plain Python: {len(result.retrieved_rules)} rules evaluated, {len(fired)} raised",
            "dim",
        )
    )
    print_findings(result)
    if quiet:
        say(style("checked, did not fire: " + " ".join(quiet), "dim"), 3)

    print(
        style("\n 5 REPORTER", "bold")
        + style("   rule, policy document, cited lines and the policy text", "dim")
    )
    for e in result.exceptions:
        print(f"   {e.rule_id} · {e.policy_doc}")
        say(style(f'"{_cut(e.evidence, 230)}"', "dim"), 5)
    print(f"\n   disposition {badge(result.disposition)} {why(result)}")
    if gold is not None:
        ok = matches_gold(result, gold)
        verdict = style("✔ match", "green") if ok else style("✖ differs", "red")
        scope = "" if gold.in_scope else " (out of the brief's scope: TIME rules)"
        print(f"   answer key  {badge(gold.disposition)} {gold_summary(gold)}  {verdict}{scope}")
        print(style("   (the answer key is used to score the demo only, never as input)", "dim"))


# --- What-if experiments -------------------------------------------------------------------------


@dataclass
class Change:
    """Edits to one receipt. Line IDs may be written short (`L2`)."""

    fields: dict[str, str] = field(default_factory=dict)  # receipt field -> raw value
    usd: dict[str, float] = field(default_factory=dict)  # line -> new USD amount
    category: dict[str, str] = field(default_factory=dict)  # line -> category
    confidence: dict[str, float] = field(default_factory=dict)  # line -> confidence
    facts: dict[str, dict[str, str]] = field(default_factory=dict)  # line -> {attribute: value}


def _parse_value(raw: str) -> object:
    return None if raw.strip().lower() in ("null", "none", "") else raw


def _line_id(rid: str, line: str, valid: set[str]) -> str:
    line_id = line.upper() if line.upper().startswith("RCP-") else f"{rid}-{line.upper()}"
    if line_id not in valid:
        raise DemoError(f"unknown line {line!r} on {rid}; lines are {', '.join(sorted(valid))}")
    return line_id


def apply_change(
    world: World, rid: str, change: Change
) -> tuple[list[Receipt], dict[str, list[ClassifiedItem]], list[str]]:
    """The batch with one receipt edited, its items' cached classification reused."""
    receipt = world.receipt(rid)
    rid = receipt.receipt_id
    data = receipt.model_dump()
    notes: list[str] = []

    edited_fields = list(change.fields)
    for name, raw in change.fields.items():
        if name not in Receipt.model_fields or name in ("receipt_id", "line_items"):
            editable = sorted(set(Receipt.model_fields) - {"receipt_id", "line_items"})
            raise DemoError(f"cannot set {name!r}; editable fields: {', '.join(editable)}")
        data[name] = _parse_value(raw)
    if "employee_country" in change.fields and "entity" not in change.fields:
        entity = ENTITY_BY_COUNTRY.get(str(data["employee_country"]).upper(), "GLOBAL")
        if entity != data["entity"]:
            data["entity"] = entity
            edited_fields.append("entity")

    items = {i.line_id: i for i in world.classified[rid]}
    lines = {line["line_id"]: line for line in data["line_items"]}
    valid = set(items)

    for line, usd in change.usd.items():
        lid = _line_id(rid, line, valid)
        row, qty = lines[lid], lines[lid]["quantity"] or 1
        fx = data["fx_rate_to_usd"] or 1.0
        notes.append(f"{_short(lid)} amount: {money(row['amount_usd'])} → {money(usd)}")
        row["amount_usd"] = usd
        row["amount"] = round(usd / fx, 2)
        row["unit_price"] = round(row["amount"] / qty, 2)
        items[lid] = items[lid].model_copy(update={"amount_usd": usd, "unit_price_usd": usd / qty})
    if change.usd:
        data["total_amount_usd"] = round(sum(line["amount_usd"] for line in lines.values()), 2)
        data["total_amount"] = round(sum(line["amount"] for line in lines.values()), 2)

    for line, category in change.category.items():
        lid = _line_id(rid, line, valid)
        if category not in load_taxonomy():
            raise DemoError(f"unknown category {category!r}; see data/category-taxonomy.md")
        notes.append(f"{_short(lid)} category: {items[lid].category} → {category}")
        items[lid] = items[lid].model_copy(
            update={"category": category, "restricted": is_restricted(category)}
        )

    for line, confidence in change.confidence.items():
        lid = _line_id(rid, line, valid)
        if not 0.0 <= confidence <= 1.0:
            raise DemoError("confidence must be between 0 and 1")
        notes.append(f"{_short(lid)} confidence: {items[lid].confidence:.2f} → {confidence:.2f}")
        items[lid] = items[lid].model_copy(update={"confidence": confidence})

    for line, facts in change.facts.items():
        lid = _line_id(rid, line, valid)
        current = items[lid].attributes.model_dump()
        for name, raw in facts.items():
            if name not in current:
                raise DemoError(f"unknown fact {name!r}; facts: {', '.join(current)}")
            notes.append(f"{_short(lid)} {name}: {current[name]!r} → {_parse_value(raw)!r}")
            current[name] = _parse_value(raw)
        items[lid] = items[lid].model_copy(
            update={"attributes": ItemAttributes.model_validate(current)}
        )

    try:
        edited = Receipt.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise DemoError(f"invalid change: {problems}") from None
    notes = [
        f"{name}: {getattr(receipt, name)!r} → {getattr(edited, name)!r}" for name in edited_fields
    ] + notes

    receipts = [edited if r.receipt_id == rid else r for r in world.receipts.values()]
    classified = {**world.classified, rid: [items[i.line_id] for i in world.classified[rid]]}
    return receipts, classified, notes


def whatif(world: World, rid: str, change: Change, *, intro: str | None = None) -> ReceiptResult:
    receipts, classified, notes = apply_change(world, rid, change)
    rid = world.receipt(rid).receipt_id
    before = world.decide()
    after = world.decide(receipts, classified)

    r = world.receipts[rid]
    print()
    print(style(f" WHAT IF · {rid} · {r.merchant_name}", "bold", "cyan"))
    if intro:
        say(intro, 3)
    for note in notes:
        print(f"   change   {style(note, 'bold')}")
    print(f"   before   {badge(before[rid].disposition)} {summary(before[rid])}")
    print(f"   after    {badge(after[rid].disposition)} {summary(after[rid])}")
    print(style(f"            {why(after[rid])}", "dim"))
    print_findings(after[rid], indent=12)
    ripple = [
        other
        for other in after
        if other != rid
        and (after[other].disposition, summary(after[other]))
        != (before[other].disposition, summary(before[other]))
    ]
    for other in ripple:
        print(
            f"   also     {other}: {badge(before[other].disposition)}→ "
            f"{badge(after[other].disposition)} {summary(after[other])}"
        )
    if ripple:
        print(style("            (cross-receipt rules see the whole batch)", "dim"))
    return after[rid]


# --- Scoreboard ----------------------------------------------------------------------------------


def scoreboard(world: World) -> dict[str, dict[str, int]]:
    """Dispositions against the answer key, recomputed live for three systems."""
    pipeline = {rid: r.disposition for rid, r in world.decide().items()}
    keyword_items = {rid: keyword_classify(r) for rid, r in world.receipts.items()}
    keyword = {rid: r.disposition for rid, r in world.decide(classified=keyword_items).items()}
    legacy = {rid: legacy_disposition(items) for rid, items in keyword_items.items()}

    board = {}
    for name, predicted in (
        ("LLM pipeline + engine", pipeline),
        ("Keyword classifier + same engine", keyword),
        ("Legacy keyword flagging", legacy),
    ):
        scored = [rid for rid in world.receipts if rid not in OUT_OF_SCOPE_RECEIPTS]
        g = {rid: world.gold[rid].disposition for rid in world.receipts}
        board[name] = {
            "correct_28": sum(predicted[rid] == g[rid] for rid in scored),
            "correct_32": sum(predicted[rid] == g[rid] for rid in world.receipts),
            "false_positives": sum(g[rid] == "pass" and predicted[rid] != "pass" for rid in scored),
            "missed": sum(g[rid] == "flag" and predicted[rid] != "flag" for rid in scored),
        }
    return board


def print_scoreboard(world: World) -> None:
    board = scoreboard(world)
    print(f"   {'system':<36}{'28 scored':>10}{'all 32':>9}{'false pos.':>12}{'missed':>9}")
    for name, s in board.items():
        print(
            f"   {name:<36}{s['correct_28']:>7}/28{s['correct_32']:>6}/32"
            f"{s['false_positives']:>9}/9{s['missed']:>7}/16"
        )


# --- Commands ------------------------------------------------------------------------------------


def cmd_list(world: World) -> None:
    results = world.decide()
    heading("Receipts (pick any one: `validator demo trace RCP-0NN`)")
    for rid, r in world.receipts.items():
        res, g = results[rid], world.gold[rid]
        ok = style("✔", "green") if matches_gold(res, g) else style("✖", "red")
        scope = style(" *", "dim") if not g.in_scope else "  "
        print(
            f" {rid}{scope}{badge(res.disposition)}{ok}  {_cut(r.merchant_name or '—', 26):<27}"
            f"{_cut(r.submitted_expense_type, 21):<22}{r.entity:<7}{money(r.total_amount_usd):>10}"
            f"  {_cut(summary(res), 34)}"
        )
    print(style(" * out of the brief's scope (TIME rules); handled as the stretch goal", "dim"))


def cmd_trace(world: World, rid: str, show_gold: bool = True) -> ReceiptResult:
    r = world.receipt(rid)
    result = world.decide()[r.receipt_id]
    print_trace(
        r,
        world.classified[r.receipt_id],
        result,
        world.gold[r.receipt_id] if show_gold else None,
        world.threshold,
    )
    return result


def _pause(enabled: bool) -> None:
    if enabled and sys.stdin.isatty():
        with contextlib.suppress(EOFError):
            input(style("\n   ⏎  next scene", "dim"))


def _scene(number: int, title: str, point: str) -> None:
    heading(f"Scene {number} · {title}")
    say(style(point, "bold"), 1)


def scene_names_lie(world: World) -> None:
    _scene(
        1,
        "Names lie",
        "RCP-004: four items with alcohol words, none of them alcohol. A keyword system flags it; "
        "the classifier reads what each item is.",
    )
    rid = "RCP-004"
    keyword_items = {i.line_id: i for i in keyword_classify(world.receipts[rid])}
    print(f"\n   {'line':<5}{'text':<30}{'keyword says':<16}{'LLM says':<16}{'confidence':>10}")
    for item in world.classified[rid]:
        kw = keyword_items[item.line_id].category
        kw_txt = style(f"{kw:<16}", "red") if kw != item.category else f"{kw:<16}"
        print(
            f"   {_short(item.line_id):<5}{_cut(item.description_raw, 29):<30}{kw_txt}"
            f"{item.category:<16}{item.confidence:>10.2f}"
        )
    keyword = world.decide(classified={**world.classified, rid: list(keyword_items.values())})
    legacy = legacy_disposition(list(keyword_items.values()))
    print()
    print(f"   legacy keyword flagging      {badge(legacy)}")
    print(
        f"   keyword + same rule engine   {badge(keyword[rid].disposition)} {summary(keyword[rid])}"
    )
    pipeline = world.decide()[rid]
    print(f"   LLM pipeline + rule engine   {badge(pipeline.disposition)} {summary(pipeline)}")
    print(f"   answer key                   {badge(world.gold[rid].disposition)}")


def scene_multilingual(world: World) -> None:
    _scene(
        2,
        "One receipt, five stages",
        "RCP-025, a German dinner: translated, classified, matched to rules, decided by code, and "
        "reported with the policy text it breaks.",
    )
    cmd_trace(world, "RCP-025")


def scene_context(world: World) -> None:
    _scene(
        3,
        "Context decides",
        "The same beer, three decisions. The classifier only says the beer is alcohol; the receipt "
        "facts and the rules decide whether it is allowed.",
    )
    entertainment = {"submitted_expense_type": "Client Entertainment", "attendee_count": "2"}
    whatif(
        world,
        "RCP-010",
        Change(fields=entertainment),
        intro="A solo dinner with a beer is ALC-01. Declare it as client entertainment for two.",
    )
    whatif(
        world,
        "RCP-010",
        Change(fields={**entertainment, "employee_country": "IN"}),
        intro="Same client dinner, but the employee is in the APAC entity (regional override).",
    )


def scene_thresholds(world: World) -> None:
    _scene(
        4,
        "Thresholds and evidence",
        "TECH-02: peripherals above $200 need a pre-approval. Compared in USD at cent precision; "
        "a carve-out applies only with the right kind of reference (EXC-02).",
    )
    whatif(world, "RCP-006", Change(usd={"L1": 200.00}), intro="The $189 dock costs exactly $200.")
    whatif(world, "RCP-006", Change(usd={"L1": 200.01}), intro="One cent more.")
    whatif(
        world,
        "RCP-006",
        Change(usd={"L1": 200.01}, fields={"pre_approval_ref": "PA-2026-0999"}),
        intro="Same $200.01 dock, now with a pre-approval reference recorded.",
    )
    whatif(
        world,
        "RCP-027",
        Change(fields={"pre_approval_ref": "PA-2026-0999"}),
        intro="Clothing needs a baggage-delay reference. Does a pre-approval waive it?",
    )


def scene_severity(world: World) -> None:
    _scene(
        5,
        "The severity ladder (EXC-01)",
        "Disposition is computed from severities, never judged: medium or worse flags, low alone "
        "goes to review, a review signal alone goes to review.",
    )
    results = world.decide()
    for rid in ("RCP-022", "RCP-031", "RCP-028", "RCP-002"):
        r = results[rid]
        print(f"\n   {rid}  {badge(r.disposition)} {summary(r)}")
        print(style(f"            {why(r)}", "dim"))
    whatif(
        world,
        "RCP-031",
        Change(fields={"trip_nights": "5"}),
        intro="LAUNDRY-01 needs a trip of four or more nights. Make the trip five nights.",
    )


def scene_batch(world: World) -> None:
    _scene(
        6,
        "Rules across receipts",
        "RCP-020 and RCP-021: two meals, same employee, merchant and day. Each is under the $75 "
        "cap; together they are not. That is a split (TIME-03), raised on both.",
    )
    results = world.decide()
    for rid in ("RCP-020", "RCP-021"):
        r, rec = results[rid], world.receipts[rid]
        print(
            f"\n   {rid}  {rec.transaction_datetime}  {money(rec.total_amount_usd)}  "
            f"{badge(r.disposition)} {summary(r)}"
        )
    say(results["RCP-020"].exceptions[0].explanation, 12)
    whatif(
        world,
        "RCP-021",
        Change(fields={"transaction_datetime": "2026-04-28T19:40:00"}),
        intro="Move the dinner to the next day. Only RCP-021 changes — watch RCP-020.",
    )


def scene_uncertainty(world: World) -> None:
    _scene(
        7,
        "When the model is unsure, or wrong",
        "Low confidence becomes a review signal, never an accusation (EXC-03). A confident wrong "
        "category is what the evaluation has to catch.",
    )
    whatif(
        world,
        "RCP-010",
        Change(confidence={"L2": 0.30}),
        intro="Suppose the classifier were only 30% sure the IPA is alcohol (threshold 0.5).",
    )
    whatif(
        world,
        "RCP-004",
        Change(category={"L1": "alcohol"}),
        intro="Suppose the classifier had made the keyword mistake: beer-battered cod as alcohol.",
    )


def scene_scoreboard(world: World) -> None:
    _scene(
        8,
        "Reproducible and measured",
        "Every model answer is in the committed cache, so this whole demo ran offline with no key. "
        "The scores below are recomputed now against the answer key.",
    )
    print()
    say(
        f"model {world.model} · {world.llm_calls} model calls, {world.cache_hits} served from "
        f"cache · spent this run {money(world.spent_this_run)} · original cost of those answers "
        f"{money(world.cost_of_responses)}",
        3,
    )
    print()
    print_scoreboard(world)
    say(
        style(
            "28 scored receipts: 9 pass, 16 flag, 3 review. Full metrics: `make evaluate`, "
            "outputs/metrics.md, and the viewer (`make viewer`).",
            "dim",
        ),
        3,
    )


SCENES = (
    scene_names_lie,
    scene_multilingual,
    scene_context,
    scene_thresholds,
    scene_severity,
    scene_batch,
    scene_uncertainty,
    scene_scoreboard,
)


def cmd_tour(world: World, scene: int | None = None, pause: bool = True) -> None:
    selected = range(1, len(SCENES) + 1) if scene is None else [scene]
    for n, number in enumerate(selected):
        if not 1 <= number <= len(SCENES):
            raise DemoError(f"scene must be 1-{len(SCENES)}")
        if n:
            _pause(pause)
        SCENES[number - 1](world)
    print()


def load_custom_receipt(path: Path) -> Receipt:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw = {k: v for k, v in raw.items() if k not in ("labels", "notes")}
    raw["line_items"] = [
        {k: v for k, v in line.items() if k != "labels"} for line in raw.get("line_items", [])
    ]
    try:
        return Receipt.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise DemoError(f"{path}: {problems}") from None


def cmd_custom(path: Path, llm: LLMClient | None = None) -> ReceiptResult:
    """A receipt nobody has seen, through the full pipeline. With a key the model is called once
    or twice (well under one cent); the answers are cached in `.demo_cache/`, so a rehearsed
    receipt replays offline."""
    receipt = load_custom_receipt(path)
    settings = load_settings()
    llm = llm or LLMClient(settings, cache_dir=DEMO_CACHE_DIR)
    normalised = normalise_receipt(receipt, llm)
    items = classify_receipt(receipt, normalised, llm)
    result = decide_all(
        [receipt],
        {receipt.receipt_id: items},
        settings.confidence_threshold,
        run="demo_custom",
        model_id=llm.model,
        prompt_versions=PROMPT_VERSIONS,
    )[0]
    print_trace(receipt, items, result, None, settings.confidence_threshold)
    usage = getattr(llm, "usage", None)
    if usage is not None:
        print(
            style(
                f"\n   model {llm.model} · {usage.calls} calls ({usage.cache_hits} from cache) · "
                f"spent {money(usage.new_cost_usd)}",
                "dim",
            )
        )
    return result


def rule_text(rule_id: str) -> str:
    rule = load_registry().get(rule_id.upper())
    if rule is None:
        raise DemoError(f"unknown rule {rule_id!r}")
    return f"{rule.rule_id} — {rule.title} ({rule.policy_doc})\n{rule.evidence}"

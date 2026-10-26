"""4. Policy engine — deterministic rule evaluation and EXC-01 disposition. No LLM calls.

Each rule is a pure function `(ReceiptContext) -> RuleHit | None` registered under its rule ID
(ADR-006). The engine takes a whole batch because some rules aggregate across receipts (ADR-016),
and it evaluates only the rules the retriever selected for each receipt (ADR-019).

Conventions (EXC-04): one hit per rule per receipt; line-level rules cite every offending line and
never a gratuity or service fee; whole-receipt rules cite no lines. Items whose category confidence
is below the threshold raise a single EXC-03 review signal and are left out of every other rule.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from . import policy_constants as pc
from .config import APPROVAL_REF_PREFIXES, COUNTRY_CURRENCY
from .models import ClassifiedItem, Receipt

# --- Data structures -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    kind: Literal["exception", "signal"]
    explanation: str
    line_ids: tuple[str, ...] = ()
    severity: str | None = None


@dataclass(frozen=True)
class Decision:
    receipt_id: str
    disposition: str
    exceptions: tuple[RuleHit, ...]
    signals: tuple[RuleHit, ...]


@dataclass
class BatchAggregates:
    """Cross-receipt state computed once per batch (ADR-016)."""

    # (employee_id, date) -> [(receipt_id, per_person_usd, international, eur_rate)]
    meal_days: dict[tuple[str, str], list[tuple[str, float, bool, float | None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    otc_by_trip: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    baggage_by_ref: dict[str, float] = field(default_factory=lambda: defaultdict(float))


@dataclass
class ReceiptContext:
    receipt: Receipt
    items: list[ClassifiedItem]
    threshold: float
    batch: BatchAggregates = field(default_factory=BatchAggregates)

    @property
    def usable(self) -> list[ClassifiedItem]:
        """Items confident enough to take part in rules (EXC-03)."""
        return [i for i in self.items if i.confidence >= self.threshold]

    @property
    def uncertain(self) -> list[ClassifiedItem]:
        return [i for i in self.items if i.confidence < self.threshold]

    def of(self, *categories: str) -> list[ClassifiedItem]:
        return [i for i in self.usable if i.category in categories]

    @property
    def approval_type(self) -> str | None:
        return approval_type(self.receipt.pre_approval_ref)

    # --- Meal helpers (MEAL-01 definitions) ---

    @property
    def is_meal_receipt(self) -> bool:
        r = self.receipt
        if r.submitted_expense_type not in pc.MEAL_EXPENSE_TYPES:
            return False
        return not r.itemized or bool(self.of("food_beverage", "alcohol"))

    @property
    def meal_spend_usd(self) -> float:
        if not self.receipt.itemized:
            return self.receipt.total_amount_usd or 0.0
        return sum(i.amount_usd for i in self.of(*pc.MEAL_SPEND_CATEGORIES))

    @property
    def meal_per_person_usd(self) -> float:
        return self.meal_spend_usd / (self.receipt.attendee_count or 1)

    @property
    def home_currency(self) -> str | None:
        return COUNTRY_CURRENCY.get(self.receipt.employee_country)

    @property
    def is_international(self) -> bool:
        return self.receipt.currency != self.home_currency

    @property
    def eur_rate(self) -> float | None:
        """USD per EUR on the transaction date. Only known for a EUR receipt (ADR-018)."""
        return self.receipt.fx_rate_to_usd if self.receipt.currency == "EUR" else None


def approval_type(ref: str | None) -> str | None:
    if not ref:
        return None
    for prefix, kind in APPROVAL_REF_PREFIXES.items():
        if ref.startswith(prefix):
            return kind
    return None


def _ids(items: Iterable[ClassifiedItem]) -> tuple[str, ...]:
    return tuple(i.line_id for i in items)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _over(amount: float, cap: float) -> bool:
    """Strictly above the cap, compared at cent precision to avoid float noise."""
    return round(amount, 2) > round(cap, 2)


def _exception(rule_id: str, explanation: str, items=(), severity: str | None = None) -> RuleHit:
    line_ids = () if rule_id in pc.WHOLE_RECEIPT_RULES else _ids(items)
    return RuleHit(rule_id, "exception", explanation, line_ids, severity or pc.SEVERITY[rule_id])


def _signal(rule_id: str, explanation: str, items=()) -> RuleHit:
    return RuleHit(rule_id, "signal", explanation, _ids(items))


# --- Rule registry -------------------------------------------------------------------------------

RuleFn = Callable[[ReceiptContext], "RuleHit | None"]
RULES: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    def register(fn: RuleFn) -> RuleFn:
        if rule_id in RULES:
            raise ValueError(f"{rule_id} registered twice")
        RULES[rule_id] = fn
        return fn

    return register


# --- Merchant category ---------------------------------------------------------------------------


@rule("MCC-01")
def mcc_01(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    if r.mcc in pc.HIGH_RISK_MCCS:
        return _exception("MCC-01", f"MCC {r.mcc} ({r.mcc_description}) is a high-risk category.")
    return None


@rule("MCC-02")
def mcc_02(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    if r.mcc in pc.MEDIUM_RISK_MCCS:
        return _signal("MCC-02", f"MCC {r.mcc} ({r.mcc_description}) is medium risk; context only.")
    return None


# --- Alcohol (ALC-01..03, MCC-03, REG-01) --------------------------------------------------------


def _alcohol_on_premise(ctx: ReceiptContext) -> bool:
    return ctx.receipt.mcc in pc.ON_PREMISE_ALCOHOL_MCCS


def _alcohol_permitted(ctx: ReceiptContext) -> bool:
    r = ctx.receipt
    return (
        r.submitted_expense_type == "Client Entertainment"
        and (r.attendee_count or 0) >= pc.ALCOHOL_MIN_ATTENDEES
    )


@rule("REG-01")
def reg_01(ctx: ReceiptContext) -> RuleHit | None:
    alcohol = ctx.of("alcohol")
    if ctx.receipt.entity == "APAC" and alcohol:
        return _exception(
            "REG-01", "Alcohol is never reimbursable for APAC-entity employees.", alcohol
        )
    return None


@rule("ALC-01")
def alc_01(ctx: ReceiptContext) -> RuleHit | None:
    alcohol = ctx.of("alcohol")
    if ctx.receipt.entity == "APAC" or not alcohol or not _alcohol_on_premise(ctx):
        return None
    if _alcohol_permitted(ctx):
        return None
    r = ctx.receipt
    return _exception(
        "ALC-01",
        f"Alcohol on a receipt declared as {r.submitted_expense_type} with attendee count "
        f"{r.attendee_count}; alcohol needs Client Entertainment with 2+ attendees.",
        alcohol,
    )


@rule("ALC-02")
def alc_02(ctx: ReceiptContext) -> RuleHit | None:
    alcohol = ctx.of("alcohol")
    if ctx.receipt.entity == "APAC" or not alcohol or not _alcohol_on_premise(ctx):
        return None
    if not _alcohol_permitted(ctx):
        return None
    attendees = ctx.receipt.attendee_count or 1
    per_attendee = sum(i.amount_usd for i in alcohol) / attendees
    if _over(per_attendee, pc.ALCOHOL_CAP_PER_ATTENDEE_USD):
        return _exception(
            "ALC-02",
            f"{_money(per_attendee)} of alcohol per attendee against the "
            f"{_money(pc.ALCOHOL_CAP_PER_ATTENDEE_USD)} cap.",
            alcohol,
        )
    return None


@rule("ALC-03")
def alc_03(ctx: ReceiptContext) -> RuleHit | None:
    alcohol = ctx.of("alcohol")
    if ctx.receipt.entity == "APAC" or not alcohol or _alcohol_on_premise(ctx):
        return None
    r = ctx.receipt
    return _exception(
        "ALC-03",
        f"Alcohol bought at MCC {r.mcc} ({r.mcc_description}), not a restaurant, bar or hotel.",
        alcohol,
    )


# --- Meals (MEAL-01, MEAL-02, REG-02, REG-03) ----------------------------------------------------


def _meal_cap_hit(ctx: ReceiptContext, rule_id: str) -> RuleHit | None:
    r = ctx.receipt
    if not ctx.is_meal_receipt or r.date is None:
        return None
    day = ctx.batch.meal_days.get((r.employee_id, r.date), [])
    day_total = sum(per_person for _, per_person, _, _ in day)
    receipts = ", ".join(rid for rid, *_ in day)

    if rule_id == "MEAL-01":
        if ctx.home_currency is None:
            return _signal(
                "MEAL-01", f"Unknown home currency for country {r.employee_country}; cap unknown."
            )
        international = any(intl for _, _, intl, _ in day)
        cap = pc.MEAL_CAP_INTERNATIONAL_USD if international else pc.MEAL_CAP_DOMESTIC_USD
        label = f"{_money(cap)} {'international' if international else 'domestic'}"
    elif rule_id == "REG-02":
        cap, label = pc.APAC_MEAL_CAP_USD, f"{_money(pc.APAC_MEAL_CAP_USD)} APAC"
    else:  # REG-03
        rate = next((rate for *_, rate in day if rate is not None), None)
        if rate is None:
            return _signal("REG-03", "No EUR rate for this date; the EUR 70 cap cannot be checked.")
        cap = pc.EMEA_MEAL_CAP_EUR * rate
        label = f"EUR {pc.EMEA_MEAL_CAP_EUR:g} ({_money(cap)}) EMEA"

    if _over(day_total, cap):
        return _exception(
            rule_id,
            f"{_money(day_total)} per person on {r.date} (receipts: {receipts}) against the "
            f"{label} daily cap.",
        )
    return None


@rule("MEAL-01")
def meal_01(ctx: ReceiptContext) -> RuleHit | None:
    return _meal_cap_hit(ctx, "MEAL-01") if ctx.receipt.entity == "GLOBAL" else None


@rule("REG-02")
def reg_02(ctx: ReceiptContext) -> RuleHit | None:
    return _meal_cap_hit(ctx, "REG-02") if ctx.receipt.entity == "APAC" else None


@rule("REG-03")
def reg_03(ctx: ReceiptContext) -> RuleHit | None:
    return _meal_cap_hit(ctx, "REG-03") if ctx.receipt.entity == "EMEA" else None


@rule("MEAL-02")
def meal_02(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    total = r.total_amount_usd or 0.0
    if (
        ctx.is_meal_receipt
        and r.attendee_count is None
        and _over(total, pc.MEAL_ATTENDEE_DOC_THRESHOLD_USD)
    ):
        return _exception(
            "MEAL-02", f"Meal receipt of {_money(total)} with no attendee count recorded."
        )
    return None


# --- Entertainment -------------------------------------------------------------------------------


@rule("ENT-01")
def ent_01(ctx: ReceiptContext) -> RuleHit | None:
    venue = [i for i in ctx.usable if i.attributes.is_entertainment_venue]
    if venue and ctx.approval_type != pc.REQUIRED_APPROVAL["ENT-01"]:
        return _exception("ENT-01", "Entertainment venue spend without a VP approval.", venue)
    return None


@rule("ENT-02")
def ent_02(ctx: ReceiptContext) -> RuleHit | None:
    gambling = ctx.of("gambling")
    if gambling:
        return _exception("ENT-02", "Gambling spend is prohibited.", gambling)
    return None


# --- Technology ----------------------------------------------------------------------------------


@rule("TECH-01")
def tech_01(ctx: ReceiptContext) -> RuleHit | None:
    devices = [i for i in ctx.of("personal_electronics") if not i.attributes.is_mobile_handset]
    if devices:
        return _exception("TECH-01", "Personal electronics are not reimbursable.", devices)
    return None


@rule("TECH-02")
def tech_02(ctx: ReceiptContext) -> RuleHit | None:
    if ctx.approval_type == pc.REQUIRED_APPROVAL["TECH-02"]:
        return None
    over = [
        i
        for i in ctx.of("computer_accessory")
        if _over(i.unit_price_usd, pc.PERIPHERAL_UNIT_CAP_USD)
    ]
    if over:
        prices = ", ".join(_money(i.unit_price_usd) for i in over)
        return _exception(
            "TECH-02",
            f"Peripheral unit price {prices} above {_money(pc.PERIPHERAL_UNIT_CAP_USD)} "
            "with no pre-approval reference.",
            over,
        )
    return None


@rule("TECH-03")
def tech_03(ctx: ReceiptContext) -> RuleHit | None:
    phones = [i for i in ctx.usable if i.attributes.is_mobile_handset]
    if phones:
        return _exception("TECH-03", "Mobile handsets are procured centrally by IT.", phones)
    return None


@rule("TECH-04")
def tech_04(ctx: ReceiptContext) -> RuleHit | None:
    subs = ctx.of("software_subscription")
    if subs and ctx.approval_type != pc.REQUIRED_APPROVAL["TECH-04"]:
        return _exception(
            "TECH-04", "Software subscription with no manager approval reference.", subs
        )
    return None


# --- Gifts ---------------------------------------------------------------------------------------


def _official_lines(ctx: ReceiptContext) -> list[ClassifiedItem]:
    return [
        i
        for i in ctx.usable
        if i.attributes.recipient_type == "government_official" and i.category != "service_fee"
    ]


def _gift_items(ctx: ReceiptContext) -> list[ClassifiedItem]:
    """Gifts under the gifts policy: bought to give, not a meal line, not a gift card."""
    declared_gifts = ctx.receipt.submitted_expense_type == "Client Gifts"
    return [
        i
        for i in ctx.usable
        if i.category not in pc.NOT_GIFT_01_CATEGORIES
        and (i.category == "gift" or i.attributes.is_gift or declared_gifts)
    ]


@rule("GIFT-04")
def gift_04(ctx: ReceiptContext) -> RuleHit | None:
    lines = _official_lines(ctx)
    if lines:
        return _exception(
            "GIFT-04", "Items of value provided to a government official or public employee.", lines
        )
    return None


@rule("GIFT-03")
def gift_03(ctx: ReceiptContext) -> RuleHit | None:
    gifts = [i for i in _gift_items(ctx) if i.attributes.recipient_type == "employee"]
    if gifts:
        return _exception("GIFT-03", "Employee gifts must be processed through HR.", gifts)
    return None


@rule("GIFT-01")
def gift_01(ctx: ReceiptContext) -> RuleHit | None:
    gifts = [
        i
        for i in _gift_items(ctx)
        if i.attributes.recipient_type not in ("government_official", "employee")
    ]
    named: dict[str, list[ClassifiedItem]] = defaultdict(list)
    unnamed: list[ClassifiedItem] = []
    for item in gifts:
        recipient = (item.attributes.recipient or "").strip().lower()
        (named[recipient] if recipient else unnamed).append(item)

    flagged: list[ClassifiedItem] = []
    reasons: list[str] = []
    for recipient, items in named.items():
        total = sum(i.amount_usd for i in items)
        if _over(total, pc.GIFT_CAP_PER_RECIPIENT_USD):
            flagged += items
            reasons.append(
                f"{_money(total)} for {items[0].attributes.recipient} against the "
                f"{_money(pc.GIFT_CAP_PER_RECIPIENT_USD)} per-recipient cap"
            )
    for item in unnamed:
        if _over(item.amount_usd, pc.GIFT_CAP_PER_RECIPIENT_USD):
            flagged.append(item)
            reasons.append(f"{_money(item.amount_usd)} unnamed gift above the cap")
        elif round(item.amount_usd, 2) >= pc.GIFT_NAMED_RECIPIENT_MIN_USD:
            flagged.append(item)
            reasons.append(f"{_money(item.amount_usd)} gift with no named recipient")
    if flagged:
        order = {i.line_id: n for n, i in enumerate(ctx.items)}
        flagged = sorted(flagged, key=lambda i: order[i.line_id])
        return _exception("GIFT-01", "; ".join(reasons) + ".", flagged)
    return None


@rule("GIFT-02")
def gift_02(ctx: ReceiptContext) -> RuleHit | None:
    cards = ctx.of("gift_card")
    if cards:
        return _exception(
            "GIFT-02", "Gift cards and cash equivalents are never reimbursable.", cards
        )
    return None


# --- Non-reimbursable items ----------------------------------------------------------------------


def _baggage_carve_out_applies(ctx: ReceiptContext) -> bool:
    """PERS-01/02 baggage-delay carve-out: needs a recorded delay reference (EXC-02), and the
    $150 allowance is shared across every receipt carrying that reference."""
    ref = ctx.receipt.pre_approval_ref
    if ctx.approval_type != pc.REQUIRED_APPROVAL["PERS-01"] or ref is None:
        return False
    return not _over(ctx.batch.baggage_by_ref[ref], pc.BAGGAGE_DELAY_ALLOWANCE_USD)


@rule("PERS-01")
def pers_01(ctx: ReceiptContext) -> RuleHit | None:
    items = ctx.of("personal_care")
    if items and not _baggage_carve_out_applies(ctx):
        return _exception(
            "PERS-01",
            "Personal care and grooming are not reimbursable; no carve-out applies.",
            items,
        )
    return None


@rule("PERS-02")
def pers_02(ctx: ReceiptContext) -> RuleHit | None:
    items = ctx.of("clothing")
    if items and not _baggage_carve_out_applies(ctx):
        return _exception(
            "PERS-02",
            "Clothing is not reimbursable and no baggage-delay reference is recorded.",
            items,
        )
    return None


@rule("PERS-03")
def pers_03(ctx: ReceiptContext) -> RuleHit | None:
    items = ctx.of("tobacco")
    if items:
        return _exception("PERS-03", "Tobacco and vaping products are not reimbursable.", items)
    return None


@rule("HOUSE-01")
def house_01(ctx: ReceiptContext) -> RuleHit | None:
    items = ctx.of("household_goods")
    if items:
        return _exception("HOUSE-01", "Household goods are not reimbursable.", items)
    return None


@rule("HEALTH-01")
def health_01(ctx: ReceiptContext) -> RuleHit | None:
    meds = ctx.of("health_otc")
    prescription = [i for i in meds if i.attributes.is_prescription]
    otc = [i for i in meds if not i.attributes.is_prescription]
    trip = ctx.receipt.trip_id

    flagged: list[ClassifiedItem] = []
    reasons: list[str] = []
    severity = "low"
    if prescription:
        flagged += prescription
        severity = pc.HEALTH_01_PRESCRIPTION_SEVERITY
        reasons.append("prescription medication is never reimbursable")
    if otc and trip is None:
        flagged += otc
        reasons.append("OTC medication on a receipt with no trip record")
    elif otc and _over(ctx.batch.otc_by_trip[trip], pc.OTC_TRIP_CAP_USD):
        flagged += otc
        reasons.append(
            f"OTC medication totals {_money(ctx.batch.otc_by_trip[trip])} on trip {trip}, "
            f"above {_money(pc.OTC_TRIP_CAP_USD)}"
        )
    if flagged:
        explanation = "; ".join(reasons).capitalize() + "."
        return _exception("HEALTH-01", explanation, flagged, severity)
    return None


@rule("LAUNDRY-01")
def laundry_01(ctx: ReceiptContext) -> RuleHit | None:
    items = ctx.of("laundry_service")
    nights = ctx.receipt.trip_nights
    if items and (nights is None or nights < pc.LAUNDRY_MIN_TRIP_NIGHTS):
        trip = f"a {nights}-night trip" if nights is not None else "a receipt with no trip record"
        return _exception(
            "LAUNDRY-01",
            f"Laundry on {trip}; requires {pc.LAUNDRY_MIN_TRIP_NIGHTS}+ nights.",
            items,
        )
    return None


# --- Documentation -------------------------------------------------------------------------------


@rule("DOC-01")
def doc_01(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    total = r.total_amount_usd or 0.0
    if not r.itemized and _over(total, pc.ITEMIZATION_THRESHOLD_USD):
        return _exception(
            "DOC-01",
            f"Non-itemized receipt of {_money(total)} above the "
            f"{_money(pc.ITEMIZATION_THRESHOLD_USD)} itemization threshold.",
        )
    return None


@rule("DOC-02")
def doc_02(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    missing = [
        name
        for name, value in (
            ("merchant name", r.merchant_name),
            ("transaction date", r.transaction_datetime),
            ("total", r.total_amount),
        )
        if value in (None, "")
    ]
    if missing:
        return _exception("DOC-02", f"Receipt is missing: {', '.join(missing)}.")
    return None


@rule("DOC-03")
def doc_03(ctx: ReceiptContext) -> RuleHit | None:
    declared = ctx.receipt.submitted_expense_type
    covers = pc.EXPENSE_TYPE_COVERS.get(declared)
    considered = [i for i in ctx.usable if i.category not in pc.DOC_03_IGNORED_CATEGORIES]
    if covers is None or not considered:
        return None
    if not any(i.category in covers for i in considered):
        found = ", ".join(sorted({i.category for i in considered}))
        return _exception("DOC-03", f"Declared as {declared}; the contents are {found}.")
    return None


@rule("DOC-04")
def doc_04(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    if r.currency == "USD":
        return None
    if r.currency is None or r.fx_rate_to_usd is None:
        return _exception(
            "DOC-04", "Foreign-currency receipt without a recorded currency or conversion rate."
        )
    return None


@rule("REG-04")
def reg_04(ctx: ReceiptContext) -> RuleHit | None:
    r = ctx.receipt
    if r.entity != "EMEA" or r.total_amount is None:
        return None
    if r.currency == "EUR":
        total_eur = r.total_amount
    else:
        return _signal("REG-04", "No EUR rate on a non-EUR receipt; VAT threshold not checked.")
    if _over(total_eur, pc.EMEA_VAT_THRESHOLD_EUR):
        return _exception(
            "REG-04",
            f"EUR {total_eur:,.2f} receipt above EUR {pc.EMEA_VAT_THRESHOLD_EUR:g} with no "
            "VAT number recorded.",
        )
    return None


# --- Batch evaluation ----------------------------------------------------------------------------


def _build_aggregates(contexts: list[ReceiptContext]) -> BatchAggregates:
    batch = BatchAggregates()
    for ctx in contexts:
        r = ctx.receipt
        ctx.batch = batch
        if ctx.is_meal_receipt and r.date:
            batch.meal_days[(r.employee_id, r.date)].append(
                (r.receipt_id, ctx.meal_per_person_usd, ctx.is_international, ctx.eur_rate)
            )
        if r.trip_id:
            otc = [i for i in ctx.of("health_otc") if not i.attributes.is_prescription]
            batch.otc_by_trip[r.trip_id] += sum(i.amount_usd for i in otc)
        if ctx.approval_type == "baggage_delay" and r.pre_approval_ref:
            spend = sum(i.amount_usd for i in ctx.of("personal_care", "clothing"))
            batch.baggage_by_ref[r.pre_approval_ref] += spend
    return batch


def disposition(exceptions: Iterable[RuleHit], signals: Iterable[RuleHit]) -> str:
    """EXC-01: computed, not judged."""
    exceptions, signals = list(exceptions), list(signals)
    if any(pc.SEVERITY_RANK[e.severity] >= pc.SEVERITY_RANK["medium"] for e in exceptions):
        return "flag"
    if exceptions or signals:
        return "review"
    return "pass"


def evaluate_batch(
    receipts: list[Receipt],
    classified: dict[str, list[ClassifiedItem]],
    threshold: float,
    retrieved: dict[str, set[str]] | None = None,
) -> dict[str, Decision]:
    """Evaluate every receipt. `retrieved=None` evaluates all rules (used by unit tests)."""
    contexts = [ReceiptContext(r, classified[r.receipt_id], threshold) for r in receipts]
    _build_aggregates(contexts)

    decisions = {}
    for ctx in contexts:
        rid = ctx.receipt.receipt_id
        rule_ids = RULES.keys() if retrieved is None else retrieved[rid] & RULES.keys()
        hits = [hit for rule_id in sorted(rule_ids) if (hit := RULES[rule_id](ctx))]
        if ctx.uncertain:
            hits.append(
                _signal(
                    "EXC-03",
                    f"Category uncertain (confidence < {threshold:g}) for "
                    f"{', '.join(_ids(ctx.uncertain))}; excluded from other rules.",
                    ctx.uncertain,
                )
            )
        exceptions = sorted(
            (h for h in hits if h.kind == "exception"),
            key=lambda h: (-pc.SEVERITY_RANK[h.severity], h.rule_id),
        )
        signals = sorted((h for h in hits if h.kind == "signal"), key=lambda h: h.rule_id)
        decisions[rid] = Decision(
            rid, disposition(exceptions, signals), tuple(exceptions), tuple(signals)
        )
    return decisions

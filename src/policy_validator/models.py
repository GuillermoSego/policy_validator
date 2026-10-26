"""Typed data at every boundary: input receipts, LLM outputs, engine outcomes, results (ADR-008)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "alcohol",
    "tobacco",
    "personal_electronics",
    "gift",
    "gift_card",
    "household_goods",
    "personal_care",
    "clothing",
    "gambling",
    "jewelry",
    "food_beverage",
    "computer_accessory",
    "office_supplies",
    "lodging",
    "ground_transport",
    "airfare",
    "laundry_service",
    "health_otc",
    "software_subscription",
    "service_fee",
    "other",
]
Severity = Literal["critical", "high", "medium", "low"]
Disposition = Literal["flag", "review", "pass"]
RecipientType = Literal["client", "employee", "government_official", "self", "unknown"]


# --- Input -------------------------------------------------------------------------------------


class LineItem(BaseModel):
    """A receipt line as submitted. Gold labels are stripped before this model is built."""

    model_config = ConfigDict(extra="forbid")

    line_id: str
    description_raw: str
    language: str
    quantity: float
    unit_price: float
    amount: float
    amount_usd: float


class Receipt(BaseModel):
    """A receipt as submitted — no `labels`, no `notes` (labels are evaluation-only)."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str
    employee_id: str
    employee_country: str
    entity: Literal["GLOBAL", "APAC", "EMEA"]
    submitted_expense_type: str
    merchant_name: str | None
    mcc: str
    mcc_description: str
    transaction_datetime: str | None
    currency: str | None
    fx_rate_to_usd: float | None
    total_amount: float | None
    total_amount_usd: float | None
    attendee_count: int | None
    trip_id: str | None
    trip_nights: int | None
    pre_approval_ref: str | None
    itemized: bool
    line_items: list[LineItem]

    @property
    def date(self) -> str | None:
        return self.transaction_datetime[:10] if self.transaction_datetime else None


# --- Pipeline stages ---------------------------------------------------------------------------


class ItemAttributes(BaseModel):
    """Facts the classifier extracts from the item text; the engine decides on them (ADR-014)."""

    is_gift: bool = False
    recipient: str | None = None
    recipient_type: RecipientType = "unknown"
    is_prescription: bool = False
    is_mobile_handset: bool = False
    is_entertainment_venue: bool = False


class ClassifiedItem(BaseModel):
    line_id: str
    description_raw: str
    description_en: str
    category: Category
    restricted: bool
    confidence: float = Field(ge=0.0, le=1.0)
    attributes: ItemAttributes = Field(default_factory=ItemAttributes)
    rationale: str | None = None

    # Copied from the input line so rules never have to look the line up again.
    quantity: float
    unit_price_usd: float
    amount_usd: float


class RetrievedRule(BaseModel):
    rule_id: str
    policy_doc: str
    reason: str


# --- Engine and output -------------------------------------------------------------------------


class PolicyException(BaseModel):
    rule_id: str
    policy_doc: str
    severity: Severity
    line_ids: list[str]
    evidence: str = ""
    explanation: str


class ReviewSignal(BaseModel):
    rule_id: str
    policy_doc: str | None = None
    reason: str
    line_ids: list[str] = Field(default_factory=list)


class ReceiptResult(BaseModel):
    """One output row. Field names follow the brief's output format; extra fields are additive."""

    receipt_id: str
    disposition: Disposition
    line_items: list[ClassifiedItem]
    exceptions: list[PolicyException]
    review_signals: list[ReviewSignal]
    retrieved_rules: list[RetrievedRule] = Field(default_factory=list)
    in_scope: bool = True
    run: str = "pipeline"  # pipeline | oracle | baseline
    model_id: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)

# Return rule engine (R0-R13 in the ShopOps brief, section 6.1)
# Pure Python: no LLM and no database access. The tool layer reads the order
# from the database, builds an OrderFacts object and calls check_return_eligibility.
from dataclasses import dataclass, field
from datetime import date

from config import SIMULATED_TODAY

TODAY = date.fromisoformat(SIMULATED_TODAY)

# ---------------------------------------------------------------------------
# Part 1: constants and data structures
# ---------------------------------------------------------------------------

# Decision codes
NOT_FOUND = "NOT_FOUND"
NOT_DELIVERED_CANCELLABLE = "NOT_DELIVERED_CANCELLABLE"
IN_TRANSIT = "IN_TRANSIT"
ALREADY_CLOSED = "ALREADY_CLOSED"
NEEDS_HUMAN = "NEEDS_HUMAN"
DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
ELIGIBLE = "ELIGIBLE"
NOT_ELIGIBLE_WINDOW = "NOT_ELIGIBLE_WINDOW"

# Approval levels (R10)
PENDING_REVIEW = "PENDING_REVIEW"
PENDING_SENIOR = "PENDING_SENIOR"

# Return reasons
REASONS_14_DAYS = {"changed_mind", "late"}    # R6
REASONS_30_DAYS = {"damaged", "wrong_item"}   # R7
VALID_REASONS = REASONS_14_DAYS | REASONS_30_DAYS

# Order statuses
NOT_DELIVERED_STATUSES = {"created", "approved", "invoiced", "processing"}  # R2
CLOSED_STATUSES = {"canceled", "unavailable"}                               # R4

# Return request statuses that block a second request (R11)
BLOCKING_REQUEST_STATUSES = {"PENDING_REVIEW", "PENDING_SENIOR", "APPROVED", "REJECTED"}

# Numbers from the rules
WINDOW_SHORT_DAYS = 14          # R6
WINDOW_LONG_DAYS = 30           # R7, and the freight-only limit in R9
LATE_DAYS_FOR_FREIGHT = 10      # R9
SENIOR_THRESHOLD_BRL = 500      # R10


@dataclass
class Item:
    price: float
    freight_value: float
    shipping_limit_date: date | None = None


@dataclass
class Payment:
    payment_type: str
    payment_value: float


@dataclass
class OrderFacts:
    order_id: str
    status: str
    purchase_date: date
    delivered_date: date | None = None   # order_delivered_customer_date
    estimated_date: date | None = None   # order_estimated_delivery_date
    carrier_date: date | None = None     # order_delivered_carrier_date
    items: list[Item] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    existing_request_statuses: list[str] = field(default_factory=list)


@dataclass
class Decision:
    code: str                            # decision code, e.g. ELIGIBLE
    rule: str                            # the rule that made the decision, e.g. "R6"
    refund_amount: float = 0.0           # R8
    approval_level: str | None = None    # R10
    freight_refund: bool = False         # R9
    voucher_amount: float = 0.0          # R12
    seller_late: bool = False            # R13
    days_since_delivery: int | None = None


# ---------------------------------------------------------------------------
# Part 2: status checks (R0-R5, R11)
# ---------------------------------------------------------------------------

def check_status(facts: OrderFacts | None, today: date = TODAY) -> Decision | None:
    """Return a final decision if a status rule applies, otherwise None."""
    # R1: the order does not belong to this customer (or does not exist)
    if facts is None:
        return Decision(NOT_FOUND, "R1")

    # R0: orders placed on or after "today" do not exist in the simulation
    if facts.purchase_date >= today:
        return Decision(NOT_FOUND, "R0")

    status = facts.status

    # R2: not delivered yet, can be cancelled instead
    if status in NOT_DELIVERED_STATUSES:
        return Decision(NOT_DELIVERED_CANCELLABLE, "R2")

    # R3: shipped, or delivered after "today" (not delivered yet in the simulation)
    if status == "shipped":
        return Decision(IN_TRANSIT, "R3")
    if status == "delivered" and facts.delivered_date is not None and facts.delivered_date > today:
        return Decision(IN_TRANSIT, "R3")

    # R4: already closed
    if status in CLOSED_STATUSES:
        return Decision(ALREADY_CLOSED, "R4")

    # R5: delivered but the delivery date is missing
    if status == "delivered" and facts.delivered_date is None:
        return Decision(NEEDS_HUMAN, "R5")

    # Any status the rules do not know: let a person decide
    if status != "delivered":
        return Decision(NEEDS_HUMAN, "UNKNOWN_STATUS")

    # R11: a return request already exists for this order
    if any(s in BLOCKING_REQUEST_STATUSES for s in facts.existing_request_statuses):
        return Decision(DUPLICATE_REQUEST, "R11")

    return None


# ---------------------------------------------------------------------------
# Part 3: window, flags, amount and approval (R6-R10, R12, R13)
# ---------------------------------------------------------------------------

def check_return_eligibility(facts: OrderFacts | None, reason: str, today: date = TODAY) -> Decision:
    """Apply R0-R13 in the order given in the brief and return one Decision."""
    if reason not in VALID_REASONS:
        raise ValueError(f"Unknown reason '{reason}'. Use one of: {sorted(VALID_REASONS)}")

    # Steps 1-3: status rules stop the evaluation
    decision = check_status(facts, today)
    if decision is not None:
        return decision

    # From here on the order is delivered, with a delivery date on or before today
    days = (today - facts.delivered_date).days   # delivery day is day 0

    # Step 4: R6 / R7 window
    if reason in REASONS_14_DAYS:
        rule, limit = "R6", WINDOW_SHORT_DAYS
    else:
        rule, limit = "R7", WINDOW_LONG_DAYS
    code = ELIGIBLE if 0 <= days <= limit else NOT_ELIGIBLE_WINDOW

    # Step 5: R9 flag (delivered 10+ days after the estimated date)
    freight_refund = (
        facts.estimated_date is not None
        and (facts.delivered_date - facts.estimated_date).days >= LATE_DAYS_FOR_FREIGHT
    )

    # Step 6: R8 refund amount
    price_total = sum(item.price for item in facts.items)
    freight_total = sum(item.freight_value for item in facts.items)
    if code == ELIGIBLE:
        refund = price_total
        if rule == "R7" or freight_refund:
            refund += freight_total
    elif freight_refund and days <= WINDOW_LONG_DAYS:
        refund = freight_total   # outside the window: freight only (R9)
    else:
        refund = 0.0
    refund = round(refund, 2)

    # Step 7: R10 approval level, only when there is something to refund
    approval = None
    if refund > 0:
        approval = PENDING_SENIOR if refund > SENIOR_THRESHOLD_BRL else PENDING_REVIEW

    # R12: the voucher share of the refund goes back as a voucher
    total_paid = sum(p.payment_value for p in facts.payments)
    voucher_paid = sum(p.payment_value for p in facts.payments if p.payment_type == "voucher")
    voucher_amount = round(refund * voucher_paid / total_paid, 2) if total_paid > 0 else 0.0

    # R13: the seller handed the order to the carrier after the shipping limit
    seller_late = facts.carrier_date is not None and any(
        item.shipping_limit_date is not None and facts.carrier_date > item.shipping_limit_date
        for item in facts.items
    )

    return Decision(
        code=code,
        rule=rule,
        refund_amount=refund,
        approval_level=approval,
        freight_refund=freight_refund,
        voucher_amount=voucher_amount,
        seller_late=seller_late,
        days_since_delivery=days,
    )
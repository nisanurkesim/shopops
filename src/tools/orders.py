# Order tools: read orders from SQLite for the customer in the session
# The customer identity always comes from the Session object (set at login),
# never from the LLM. A customer can only see their own orders (rule R1).
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from config import DB_PATH
from src.returns import (
    ALREADY_CLOSED, DUPLICATE_REQUEST, ELIGIBLE, IN_TRANSIT, NEEDS_HUMAN, NOT_DELIVERED_CANCELLABLE,
    NOT_ELIGIBLE_WINDOW, NOT_FOUND, PENDING_REVIEW, PENDING_SENIOR, TODAY, Item, OrderFacts, Payment,
    check_return_eligibility as run_return_rules,
)

# Same message whether the order does not exist or belongs to someone else (R1)
NOT_FOUND_MESSAGE = "Bu numarayla size ait bir sipariş bulunamadı."
MAX_LIST_LIMIT = 20
CURRENCY = "BRL"   # Olist prices are in Brazilian real
ORDER_REF_CHARS = 8   # short order number shown to the customer

# Turkish text next to every code, so the agent does not show codes to the customer
STATUS_TEXT = {
    "created": "Oluşturuldu", "approved": "Onaylandı", "invoiced": "Faturalandı",
    "processing": "Hazırlanıyor", "shipped": "Kargoda", "delivered": "Teslim edildi",
    "canceled": "İptal edildi", "unavailable": "Ürün temin edilemedi",
}
DECISION_TEXT = {
    ELIGIBLE: "İade edilebilir",
    NOT_ELIGIBLE_WINDOW: "İade süresi geçmiş",
    IN_TRANSIT: "Sipariş henüz teslim edilmedi; iade teslimden sonra açılabilir",
    NOT_DELIVERED_CANCELLABLE: "Sipariş henüz kargoya verilmedi; iade yerine iptal edilebilir",
    ALREADY_CLOSED: "Sipariş iptal edilmiş veya kapanmış; iade talebi açılamaz",
    NEEDS_HUMAN: "Bu sipariş için kararı bir temsilci vermeli",
    DUPLICATE_REQUEST: "Bu sipariş için zaten bir iade talebi var",
}
APPROVAL_TEXT = {
    PENDING_REVIEW: "Temsilci onayı bekleyecek",
    PENDING_SENIOR: "Kıdemli temsilci onayı bekleyecek",
}


@dataclass(frozen=True)
class Session:
    """Who is logged in. Set by the login step, never by the LLM."""
    customer_unique_id: str


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def connect_read_only(db_path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row   # rows can be read by column name
    return con


def to_date(value) -> date | None:
    """'2018-08-27 15:20:00' -> date(2018, 8, 27). Missing values -> None."""
    if value is None or isinstance(value, float) or value == "":
        return None   # NULL in SQLite, or NaN left over from pandas
    return date.fromisoformat(str(value)[:10])


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


ORDER_FOR_CUSTOMER_SQL = """
SELECT o.order_id, o.order_status, o.order_purchase_timestamp,
       o.order_delivered_customer_date, o.order_estimated_delivery_date,
       o.order_delivered_carrier_date
FROM orders AS o
JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.order_id = ? AND c.customer_unique_id = ?
"""


def fetch_order_facts(con: sqlite3.Connection, order_id: str, customer_unique_id: str) -> OrderFacts | None:
    """Everything the rule engine needs about one order, or None if it is not this customer's."""
    row = con.execute(ORDER_FOR_CUSTOMER_SQL, (order_id, customer_unique_id)).fetchone()
    if row is None:
        return None

    items = [
        Item(price=r["price"], freight_value=r["freight_value"],
             shipping_limit_date=to_date(r["shipping_limit_date"]))
        for r in con.execute(
            "SELECT price, freight_value, shipping_limit_date FROM order_items WHERE order_id = ?",
            (order_id,))
    ]
    payments = [
        Payment(payment_type=r["payment_type"], payment_value=r["payment_value"])
        for r in con.execute(
            "SELECT payment_type, payment_value FROM payments WHERE order_id = ?", (order_id,))
    ]
    request_statuses = [
        r["status"] for r in con.execute(
            "SELECT status FROM return_requests WHERE order_id = ?", (order_id,))
    ]

    return OrderFacts(
        order_id=row["order_id"],
        status=row["order_status"],
        purchase_date=to_date(row["order_purchase_timestamp"]),
        delivered_date=to_date(row["order_delivered_customer_date"]),
        estimated_date=to_date(row["order_estimated_delivery_date"]),
        carrier_date=to_date(row["order_delivered_carrier_date"]),
        items=items,
        payments=payments,
        existing_request_statuses=request_statuses,
    )


def customer_view(status: str, delivered_date: date | None) -> tuple[str, date | None]:
    """Status as the customer should see it on SIMULATED_TODAY (rule R3).

    An order marked 'delivered' with a delivery date after today is not
    delivered yet in the simulation, so it is shown as 'shipped'.
    """
    if status == "delivered" and delivered_date is not None and delivered_date > TODAY:
        return "shipped", None
    return status, delivered_date


def not_found() -> dict:
    return {"error": NOT_FOUND, "message": NOT_FOUND_MESSAGE}


def order_ref(order_id: str) -> str:
    """The short order number the agent writes in its answer."""
    return order_id[:ORDER_REF_CHARS]


def is_past_estimate(status: str, estimated: date | None) -> bool:
    """Still in transit although the estimated delivery date has passed (prompt rule 6)."""
    return status == "shipped" and estimated is not None and estimated < TODAY


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_order_status(session: Session, order_id: str, db_path: Path = DB_PATH) -> dict:
    """Status, dates and items of one of the customer's orders."""
    with closing(connect_read_only(db_path)) as con:
        facts = fetch_order_facts(con, order_id, session.customer_unique_id)
    if facts is None:
        return not_found()

    status, delivered = customer_view(facts.status, facts.delivered_date)
    return {
        "order_id": facts.order_id,
        "order_ref": order_ref(facts.order_id),
        "status": status,
        "status_text": STATUS_TEXT.get(status, status),
        "purchase_date": iso(facts.purchase_date),
        "estimated_delivery_date": iso(facts.estimated_date),
        "delivered_date": iso(delivered),
        "past_estimated_date": is_past_estimate(status, facts.estimated_date),
        "item_count": len(facts.items),
        "items_total": round(sum(i.price for i in facts.items), 2),
        "freight_total": round(sum(i.freight_value for i in facts.items), 2),
        "currency": CURRENCY,
    }


CUSTOMER_ORDERS_SQL = """
SELECT o.order_id, o.order_status, o.order_purchase_timestamp,
       o.order_delivered_customer_date,
       (SELECT COUNT(*) FROM order_items AS i WHERE i.order_id = o.order_id) AS item_count,
       (SELECT COALESCE(SUM(i.price), 0) FROM order_items AS i WHERE i.order_id = o.order_id) AS items_total
FROM orders AS o
JOIN customers AS c ON o.customer_id = c.customer_id
WHERE c.customer_unique_id = ?
ORDER BY o.order_purchase_timestamp DESC
"""


def list_customer_orders(session: Session, limit: int = 5, status: str | None = None,
                         db_path: Path = DB_PATH) -> dict:
    """The customer's orders, newest first. Optional filter on the status the customer sees."""
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    with closing(connect_read_only(db_path)) as con:
        rows = con.execute(CUSTOMER_ORDERS_SQL, (session.customer_unique_id,)).fetchall()

    orders = []
    for r in rows:
        shown_status, _ = customer_view(r["order_status"], to_date(r["order_delivered_customer_date"]))
        if status is not None and shown_status != status:
            continue
        orders.append({
            "order_id": r["order_id"],
            "order_ref": order_ref(r["order_id"]),
            "status": shown_status,
            "status_text": STATUS_TEXT.get(shown_status, shown_status),
            "purchase_date": iso(to_date(r["order_purchase_timestamp"])),
            "item_count": r["item_count"],
            "items_total": round(r["items_total"], 2),
        })
    return {"orders": orders[:limit], "total_orders": len(orders), "currency": CURRENCY}


def check_return_eligibility(session: Session, order_id: str, reason: str,
                             db_path: Path = DB_PATH) -> dict:
    """Run the return rules (R0-R13) for one of the customer's orders. Read only."""
    with closing(connect_read_only(db_path)) as con:
        facts = fetch_order_facts(con, order_id, session.customer_unique_id)
    try:
        decision = run_return_rules(facts, reason)
    except ValueError as e:
        return {"error": "INVALID_REASON", "message": str(e)}
    if decision.code == NOT_FOUND:
        return not_found()   # do not reveal whether it was R0 or R1

    result = {"order_id": order_id, "order_ref": order_ref(order_id), "reason": reason,
              **asdict(decision), "currency": CURRENCY,
              "decision_text": DECISION_TEXT.get(decision.code, decision.code)}
    if decision.approval_level:
        result["approval_text"] = APPROVAL_TEXT[decision.approval_level]
    if decision.code == IN_TRANSIT:
        # The return tool must also say when a parcel looks lost (error analysis 4)
        status, _ = customer_view(facts.status, facts.delivered_date)
        result["past_estimated_date"] = is_past_estimate(status, facts.estimated_date)
    return result
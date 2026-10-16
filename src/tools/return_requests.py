# Return requests behind human approval (HITL, guardrail G1)
# Step 1, prepare_return_request: called by the agent. Checks the rules and creates a
#   PendingReturn with a secret token. Nothing is written. The token is never shown to the LLM.
# Step 2, create_return_request: called by the interface after the customer confirms.
#   Writes one row to return_requests only if the token matches.
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from config import DB_PATH, SIMULATED_TODAY
from src.returns import ELIGIBLE, NOT_ELIGIBLE_WINDOW
from src.tools.orders import APPROVAL_TEXT, CURRENCY, Session, check_return_eligibility, order_ref

APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass
class PendingReturn:
    """A return request waiting for the customer's confirmation. Kept outside the LLM."""
    token: str
    customer_unique_id: str
    order_id: str
    reason: str
    refund_amount: float
    status: str   # PENDING_REVIEW or PENDING_SENIOR (rule R10)

    def summary(self) -> dict:
        """What the LLM and the customer may see. No token."""
        return {
            "order_id": self.order_id,
            "order_ref": order_ref(self.order_id),
            "reason": self.reason,
            "refund_amount": self.refund_amount,
            "currency": CURRENCY,
            "approval_level": self.status,
            "approval_text": APPROVAL_TEXT[self.status],
        }


def prepare_return_request(session: Session, order_id: str, reason: str,
                           db_path: Path = DB_PATH) -> tuple[dict, PendingReturn | None]:
    """Check the rules and prepare a request for confirmation. Writes nothing."""
    result = check_return_eligibility(session, order_id, reason, db_path=db_path)
    if "error" in result:
        return result, None   # NOT_FOUND or INVALID_REASON, passed on as it is
    if result["refund_amount"] <= 0 or result["approval_level"] is None:
        return {
            "error": "NOT_ELIGIBLE",
            "code": result["code"],
            "message": "A return request cannot be created for this order.",
        }, None

    pending = PendingReturn(
        token=secrets.token_urlsafe(16),
        customer_unique_id=session.customer_unique_id,
        order_id=order_id,
        reason=reason,
        refund_amount=result["refund_amount"],
        status=result["approval_level"],
    )
    message = ("The request is NOT created yet. The customer must confirm it in the interface. "
               "Show the summary and wait for the confirmation.")
    return {"status": APPROVAL_REQUIRED, **pending.summary(), "message": message}, pending


def create_return_request(session: Session, pending: PendingReturn | None, token: str,
                          db_path: Path = DB_PATH) -> dict:
    """Write the request. Only the interface calls this, after the customer confirms."""
    if (pending is None
            or not secrets.compare_digest(token, pending.token)
            or pending.customer_unique_id != session.customer_unique_id):
        return {"error": APPROVAL_REQUIRED, "message": "No valid customer approval for this request."}

    # Check the rules again right before writing: the situation may have changed (R11)
    result = check_return_eligibility(session, pending.order_id, pending.reason, db_path=db_path)
    if (result.get("code") not in (ELIGIBLE, NOT_ELIGIBLE_WINDOW)
            or result.get("refund_amount") != pending.refund_amount):
        return {"error": "NOT_ELIGIBLE", "code": result.get("code") or result.get("error"),
                "message": "The order is no longer eligible for this request."}

    # The only write in the project, and only into return_requests
    with closing(sqlite3.connect(db_path)) as con, con:
        cur = con.execute(
            "INSERT INTO return_requests (order_id, reason, refund_amount, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (pending.order_id, pending.reason, pending.refund_amount, pending.status, SIMULATED_TODAY),
        )
        request_id = cur.lastrowid
    return {"return_request_id": request_id, **pending.summary()}
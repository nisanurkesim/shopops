# shopops-orders: the order tools of the Support Agent as an MCP server (stdio transport)
# Started by the agent as a separate process, one per logged-in customer:
#   python -m src.mcp_servers.shopops_orders --customer <customer_unique_id> --db <path>
# Identity (R1): the customer is fixed when the process starts. No tool has a customer
#   parameter, so the LLM cannot ask for someone else's orders.
# Approval (G1): create_return_request only prepares a request and returns an approval
#   token. confirm_return_request writes it only with that token. The agent keeps the token
#   away from the LLM, and only the interface calls confirm_return_request.
# Both checks run here, in the server, not in the agent (brief 5.3).
import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import DB_PATH
from src.tools.orders import Session, check_return_eligibility as check_eligibility
from src.tools.orders import get_order_status as order_status, list_customer_orders as customer_orders
from src.tools.return_requests import PendingReturn, create_return_request as write_request
from src.tools.return_requests import prepare_return_request

SERVER_NAME = "shopops-orders"


class OrdersService:
    """The tools for one customer. The MCP server wraps one of these; the tests use it directly."""

    def __init__(self, customer_unique_id: str, db_path: Path = DB_PATH):
        self.session = Session(customer_unique_id)
        self.db_path = Path(db_path)
        self.pending: PendingReturn | None = None   # at most one request waits for approval

    def get_order_status(self, order_id: str) -> dict:
        return order_status(self.session, order_id, db_path=self.db_path)

    def list_customer_orders(self, limit: int = 5, status: str | None = None) -> dict:
        return customer_orders(self.session, limit=limit, status=status, db_path=self.db_path)

    def check_return_eligibility(self, order_id: str, reason: str) -> dict:
        return check_eligibility(self.session, order_id, reason, db_path=self.db_path)

    def create_return_request(self, order_id: str, reason: str) -> dict:
        """Prepare a request. Nothing is written; the result carries the approval token."""
        result, pending = prepare_return_request(self.session, order_id, reason, db_path=self.db_path)
        self.pending = pending
        if pending is not None:
            result = {**result, "approval_token": pending.token}
        return result

    def confirm_return_request(self, approval_token: str, approved: bool) -> dict:
        """The customer's answer. Writes the prepared request only with the right token."""
        pending, self.pending = self.pending, None
        if pending is None:
            return {"error": "NO_PENDING_REQUEST", "message": "No return request waits for approval."}
        if not approved:
            return {"status": "CANCELLED_BY_CUSTOMER", **pending.summary()}
        return write_request(self.session, pending, approval_token, db_path=self.db_path)


def build_server(service: OrdersService) -> FastMCP:
    mcp = FastMCP(SERVER_NAME, log_level="WARNING")   # no log line for every call

    @mcp.tool()
    def get_order_status(order_id: str) -> dict:
        """Status, dates and totals of one of the logged-in customer's orders."""
        return service.get_order_status(order_id)

    @mcp.tool()
    def list_customer_orders(limit: int = 5, status: str | None = None) -> dict:
        """The logged-in customer's orders, newest first."""
        return service.list_customer_orders(limit, status)

    @mcp.tool()
    def check_return_eligibility(order_id: str, reason: str) -> dict:
        """Run the return rules (R0-R13) for one of the customer's orders. Writes nothing."""
        return service.check_return_eligibility(order_id, reason)

    @mcp.tool()
    def create_return_request(order_id: str, reason: str) -> dict:
        """Prepare a return request for the customer's approval. Writes nothing."""
        return service.create_return_request(order_id, reason)

    @mcp.tool()
    def confirm_return_request(approval_token: str, approved: bool) -> dict:
        """The customer's answer to a prepared request. Called by the interface, not the LLM."""
        return service.confirm_return_request(approval_token, approved)

    return mcp


def main():
    parser = argparse.ArgumentParser(description="shopops-orders MCP server (stdio)")
    parser.add_argument("--customer", required=True, help="customer_unique_id of the logged-in customer")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite database")
    args = parser.parse_args()
    build_server(OrdersService(args.customer, args.db)).run(transport="stdio")


if __name__ == "__main__":
    main()

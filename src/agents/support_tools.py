# Tools of the Support Agent: what the LLM sees, and how each call is run
# The LLM never passes a customer id. Every tool gets the customer from the Session.
from google.genai import types

from src.knowledge.policies import search_policies
from src.returns import VALID_REASONS
from src.tools.orders import Session, check_return_eligibility, get_order_status, list_customer_orders

ORDER_STATUSES = ["created", "approved", "invoiced", "processing",
                  "shipped", "delivered", "canceled", "unavailable"]

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="list_customer_orders",
        description=(
            "List the logged-in customer's orders, newest first. "
            "Use it when the customer talks about an order without giving its number."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many orders to return (1-20). Default 5."},
                "status": {"type": "string", "enum": ORDER_STATUSES,
                           "description": "Only orders with this status."},
            },
        },
    ),
    types.FunctionDeclaration(
        name="get_order_status",
        description="Status, dates and totals of one of the customer's orders.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The 32-character order id."},
            },
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="check_return_eligibility",
        description=(
            "Decide with the store's return rules whether an order can be returned, "
            "and the refund amount. Always use this for return questions; never decide yourself."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The 32-character order id."},
                "reason": {
                    "type": "string",
                    "enum": sorted(VALID_REASONS),
                    "description": (
                        "changed_mind: customer changed their mind or the size did not fit; "
                        "late: arrived late and the customer no longer wants it; "
                        "damaged: broken or unusable; wrong_item: a different product arrived."
                    ),
                },
            },
            "required": ["order_id", "reason"],
        },
    ),
    types.FunctionDeclaration(
        name="search_policies",
        description=(
            "Search the store's policy documents (returns, shipping, cancellation, "
            "payments, privacy). Returns the best matching sections with their titles."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The question in Turkish."},
            },
            "required": ["query"],
        },
    ),
]


def execute_tool(session: Session, name: str, args: dict) -> dict:
    """Run one tool call from the LLM. Always returns a dict, never raises."""
    try:
        if name == "list_customer_orders":
            return list_customer_orders(session, limit=args.get("limit", 5), status=args.get("status"))
        if name == "get_order_status":
            return get_order_status(session, args["order_id"])
        if name == "check_return_eligibility":
            return check_return_eligibility(session, args["order_id"], args["reason"])
        if name == "search_policies":
            hits = search_policies(args["query"], k=3)
            return {"results": [
                {"title": h["title"], "section": h["section"], "text": h["text"], "score": h["score"]}
                for h in hits
            ]}
        return {"error": "UNKNOWN_TOOL", "message": f"There is no tool called '{name}'."}
    except KeyError as e:
        return {"error": "MISSING_ARGUMENT", "message": f"Missing argument: {e}"}
    except Exception as e:   # a tool failure must not crash the agent
        return {"error": "TOOL_FAILED", "message": str(e)}
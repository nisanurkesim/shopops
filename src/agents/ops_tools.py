# Tools of the Ops Data Agent: what the LLM sees, and how each call is run
# These tools exist only in the ops agent. The Support Agent (customer session) has no
# way to reach them (G5).
from google.genai import types

from src.guardrails.injection_flag import flag_result
from src.tools.metrics import list_metrics, load_semantic_layer, run_metric
from src.tools.run_sql import run_sql

_LAYER = load_semantic_layer()
METRIC_NAMES = list(_LAYER["metrics"])
DIMENSIONS = list(_LAYER["dimensions"])

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="list_metrics",
        description="The defined metrics with their descriptions and the dimensions each one allows.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="run_metric",
        description=(
            "Compute a defined metric with its official SQL. Optional filters (one value per "
            "dimension) and up to two group_by dimensions. With group_by, min_n keeps groups with "
            "at least that many orders, sort orders the groups by the metric and limit keeps the "
            "first rows (for example 'top 5 categories with at least 100 orders'). Returns the "
            "rows, the SQL and a caveat. Use this whenever the question matches a metric."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "metric_name": {"type": "string", "enum": METRIC_NAMES},
                "filters": {
                    "type": "object",
                    "description": "Dimension -> value. purchase_month is YYYY-MM, states are two letters (SP).",
                    "properties": {d: {"type": "string"} for d in DIMENSIONS},
                },
                "group_by": {"type": "array", "items": {"type": "string", "enum": DIMENSIONS}, "maxItems": 2},
                "min_n": {"type": "integer", "description": "Only groups with at least this many orders."},
                "sort": {"type": "string", "enum": ["desc", "asc"], "description": "Order the groups by the metric."},
                "limit": {"type": "integer", "description": "Keep only the first rows (1-1000)."},
            },
            "required": ["metric_name"],
        },
    ),
    types.FunctionDeclaration(
        name="run_sql",
        description=(
            "Run one read-only SELECT on the order database, only when no defined metric fits "
            "the question. At most 1000 rows. Returns the rows or an error message you can use "
            "to correct the query."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "One SQLite SELECT statement."}},
            "required": ["query"],
        },
    ),
]


def execute_ops_tool(name: str, args: dict) -> dict:
    """Run one tool call from the LLM. Always returns a dict, never raises."""
    try:
        if name == "list_metrics":
            return list_metrics()
        if name == "run_metric":
            return run_metric(args["metric_name"], args.get("filters") or {}, args.get("group_by") or [],
                              min_n=args.get("min_n"), sort=args.get("sort"), limit=args.get("limit"))
        if name == "run_sql":
            # Rows can hold review texts written by customers: flagged before the model reads them (A5)
            return flag_result(run_sql(args["query"]))
        return {"error": "UNKNOWN_TOOL", "message": f"There is no tool called '{name}'."}
    except KeyError as e:
        return {"error": "MISSING_ARGUMENT", "message": f"Missing argument: {e}"}
    except Exception as e:   # a tool failure must not crash the agent
        return {"error": "TOOL_FAILED", "message": str(e)}

# SQL validator for the Ops Data Agent (guardrail G3)
# Every query from the agent passes through here before it reaches the database.
# The SQL is parsed with sqlglot, not searched with regular expressions, so tricks
# like comments, odd spacing or a second statement after ";" do not get through.
# Rules: one statement; only SELECT (WITH and UNION allowed); no statement that writes
# or changes the database anywhere in the tree; only the allowed tables; no dangerous
# functions; at most MAX_ROWS rows (LIMIT added or lowered).
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

MAX_ROWS = 1000

# Order data the ops questions need. return_requests and SQLite's own tables are left out.
ALLOWED_TABLES = {
    "orders", "order_items", "customers", "products", "sellers", "payments", "reviews",
    "category_translation",
}

# Node types that must not appear anywhere in the query, not even inside a subquery
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
    exp.Attach, exp.Detach, exp.Pragma, exp.Command, exp.Transaction, exp.Commit, exp.Rollback,
)

# Functions that read or write files or load code
FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


def reject(code: str, message: str) -> dict:
    return {"ok": False, "error": code, "message": message}


def validate_sql(query: str) -> dict:
    """Check one query. Returns {"ok": True, "sql": safe_sql} or {"ok": False, "error", "message"}."""
    if not isinstance(query, str) or not query.strip():
        return reject("EMPTY_QUERY", "The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(query, read="sqlite") if s is not None]
    except ParseError as e:
        return reject("INVALID_SQL", f"The query could not be parsed: {str(e)[:200]}")
    if len(statements) != 1:
        return reject("MULTIPLE_STATEMENTS", "Send exactly one statement.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        return reject("NOT_SELECT", "Only SELECT queries are allowed.")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return reject("FORBIDDEN_STATEMENT", f"{type(node).__name__.upper()} is not allowed.")
        if isinstance(node, exp.Func) and node.name.lower() in FORBIDDEN_FUNCTIONS:
            return reject("FORBIDDEN_FUNCTION", f"The function {node.name} is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.db and table.db.lower() != "main":
            return reject("FORBIDDEN_TABLE", f"Only tables of the main database are allowed, not {table.db}.")
        if name not in ALLOWED_TABLES and name not in cte_names:
            return reject("FORBIDDEN_TABLE", f"The table {table.name} is not allowed. "
                                             f"Allowed: {', '.join(sorted(ALLOWED_TABLES))}.")

    # At most MAX_ROWS rows: add a LIMIT, or lower one that is larger
    limit = tree.args.get("limit")
    limit_value = limit.expression if isinstance(limit, exp.Limit) else None
    if limit_value is None or not (isinstance(limit_value, exp.Literal) and limit_value.is_int
                                   and int(limit_value.name) <= MAX_ROWS):
        tree = tree.limit(MAX_ROWS)
    return {"ok": True, "sql": tree.sql(dialect="sqlite")}

# SQL validator for the Ops Data Agent (guardrail G3)
# Every query from the agent passes through here before it reaches the database.
# The SQL is parsed with sqlglot, not searched with regular expressions, so tricks
# like comments, odd spacing or a second statement after ";" do not get through.
# Rules: one statement; only SELECT (WITH and UNION allowed); no statement that writes
# or changes the database anywhere in the tree; only the allowed tables; no dangerous
# functions; no customer, order or review id and no customer zip code in the result, and no
# SELECT * (the columns must be named); at most MAX_ROWS rows (LIMIT added or lowered).
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

# Columns that point to one customer, order or review. A query may use them to join, filter,
# group or count, but they must not be in the result. Seller and product ids are business
# data and stay allowed, and so does the city.
BLOCKED_OUTPUT_COLUMNS = {"customer_id", "customer_unique_id", "order_id", "review_id", "customer_zip_code_prefix"}

# Parts of a result column that give a number or true/false instead of the value itself:
# COUNT(order_id), order_id = '...', order_id IN (...), EXISTS (...).
# MIN, MAX and GROUP_CONCAT are not here: they return the id itself.
SAFE_NODES = (exp.Count, exp.Predicate)


def reject(code: str, message: str) -> dict:
    return {"ok": False, "error": code, "message": message}


def output_selects(query: exp.Expression) -> list[exp.Select]:
    """The SELECTs whose rows make up the result: the query itself, or every branch of a UNION."""
    if isinstance(query, exp.Subquery):
        return output_selects(query.this)
    if isinstance(query, exp.SetOperation):
        return output_selects(query.left) + output_selects(query.right)
    return [query] if isinstance(query, exp.Select) else []


def is_star(node: exp.Expression) -> bool:
    """* or t.*"""
    return isinstance(node, exp.Star) or (isinstance(node, exp.Column) and isinstance(node.this, exp.Star))


def value_nodes(expression: exp.Expression):
    """The columns and * whose value ends up in this result column. A scalar subquery gives
    the columns of its own result. The parts in SAFE_NODES are skipped."""
    stack = [expression]
    while stack:
        node = stack.pop()
        if isinstance(node, SAFE_NODES):
            continue
        if isinstance(node, (exp.Subquery, exp.Query)):
            for select in output_selects(node):
                stack.extend(select.expressions)
        elif is_star(node) or isinstance(node, exp.Column):
            yield node
        elif isinstance(node, exp.Window):
            stack.append(node.this)   # PARTITION BY and ORDER BY only order the rows
        else:
            stack.extend(node.iter_expressions())


def alias_columns(node: exp.Expression) -> list[str]:
    """Column names given with the alias, as in WITH t(a, b) AS (...)."""
    alias = node.args.get("alias")
    return [c.name.lower() for c in alias.columns] if isinstance(alias, exp.TableAlias) else []


def derived_sources(select: exp.Select, table: str, ctes: dict) -> list[tuple[list[str], exp.Expression]]:
    """The CTEs and subqueries in the FROM and JOINs of a SELECT that a column can come from.
    table: the column's table name or alias; empty when the column has none."""
    sources = []
    for item in [select.args.get("from_"), *(select.args.get("joins") or [])]:
        node = item.this if item is not None else None
        if isinstance(node, exp.Subquery):
            source = (alias_columns(node), node.this)
        elif isinstance(node, exp.Table) and not node.db and node.name.lower() in ctes:
            source = ctes[node.name.lower()]
        else:
            continue   # a real table: its columns are checked by name
        if not table or node.alias_or_name.lower() == table:
            sources.append(source)
    return sources


def shown_through(name: str, table: str, select: exp.Select, ctes: dict, seen: set) -> str | None:
    """The blocked column behind the column `name` of a CTE or subquery in this SELECT, or None.
    Catches a new name: WITH t AS (SELECT order_id AS x FROM orders) SELECT x FROM t."""
    if select is None or (id(select), table, name) in seen:
        return None   # seen: a recursive CTE refers to itself
    seen.add((id(select), table, name))
    for columns, source in derived_sources(select, table, ctes):
        for branch in output_selects(source):
            if columns:
                targets = branch.expressions[columns.index(name):][:1] if name in columns else []
            else:
                targets = [e for e in branch.expressions if e.alias_or_name.lower() == name]
                if any(is_star(e) for e in branch.expressions):
                    # SELECT * in the source passes the name on unchanged: look one level deeper
                    found = shown_through(name, "", branch, ctes, seen)
                    if found:
                        return found
            for target in targets:
                for node in value_nodes(target):
                    found = None if is_star(node) else hidden_column(node, ctes, seen)
                    if found:
                        return found
    return None


def hidden_column(node: exp.Column, ctes: dict, seen: set) -> str | None:
    """The blocked column that this result column shows, directly or through a CTE or subquery."""
    name = node.name.lower()
    if name in BLOCKED_OUTPUT_COLUMNS:
        return name
    return shown_through(name, node.table.lower(), node.parent_select, ctes, seen)


def check_result_columns(tree: exp.Query) -> dict | None:
    """No SELECT * and no blocked column in the result. Returns a rejection, or None."""
    ctes = {cte.alias_or_name.lower(): (alias_columns(cte), cte.this) for cte in tree.find_all(exp.CTE)}
    for select in output_selects(tree):
        for expression in select.expressions:
            for node in value_nodes(expression):
                if is_star(node):
                    return reject("SELECT_STAR", "Name the columns you need instead of *. COUNT(*) is fine.")
                name = hidden_column(node, ctes, set())
                if name:
                    return reject("ID_COLUMN", f"The result must not show {name}: customer, order and review "
                                               "ids and the customer zip code stay hidden. Use them only to join, "
                                               f"filter, group or count, for example COUNT(DISTINCT {name}).")
    return None


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

    # After the table check, so a hidden table is reported as FORBIDDEN_TABLE even with SELECT *
    rejected = check_result_columns(tree)
    if rejected:
        return rejected

    # At most MAX_ROWS rows: add a LIMIT, or lower one that is larger
    limit = tree.args.get("limit")
    limit_value = limit.expression if isinstance(limit, exp.Limit) else None
    if limit_value is None or not (isinstance(limit_value, exp.Literal) and limit_value.is_int
                                   and int(limit_value.name) <= MAX_ROWS):
        tree = tree.limit(MAX_ROWS)
    return {"ok": True, "sql": tree.sql(dialect="sqlite")}

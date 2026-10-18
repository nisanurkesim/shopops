# run_sql: free SQL for the Ops Data Agent, behind four layers (guardrail G3)
# 1. The validator (src/guardrails/sql_validator.py) checks the query before it runs. It also
#    keeps customer, order and review ids and the customer zip code out of the result.
# 2. The database is opened read-only (mode=ro), so nothing can be written.
# 3. ATTACH is switched off on the connection (SQLITE_LIMIT_ATTACHED = 0): mode=ro alone
#    does not stop ATTACH from opening or creating another file.
# 4. A second check on the values: any customer, order or review id still in the rows (a
#    trick the validator did not see) is replaced by '#' + its hash before the agent reads it.
# A query that runs longer than TIMEOUT_S is stopped. SQLite errors (for example a wrong
# column name) are returned to the agent so it can correct the query (G4).
import re
import sqlite3
import time
from pathlib import Path

from config import DB_PATH
from src.agents.trace import hash_id
from src.guardrails.sql_validator import MAX_ROWS, validate_sql

TIMEOUT_S = 10

# Olist ids are 32 hex characters. Seller and product ids look the same, so a value is only
# hidden when it is found in one of these columns.
HEX_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
ID_COLUMNS = [("orders", "order_id"), ("customers", "customer_id"),
              ("customers", "customer_unique_id"), ("reviews", "review_id")]


def connect_for_queries(db_path: Path = DB_PATH, timeout_s: float = TIMEOUT_S) -> sqlite3.Connection:
    """A read-only connection with ATTACH switched off and a time limit per query."""
    con = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    deadline = time.monotonic() + timeout_s
    # SQLite calls this every 10,000 steps; a non-zero return stops the query
    con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    return con


def known_ids(con: sqlite3.Connection, candidates: set[str]) -> set[str]:
    """The candidates that are customer, order or review ids in the database."""
    found, values = set(), sorted(candidates)
    for table, column in ID_COLUMNS:
        for start in range(0, len(values), 500):
            chunk = values[start:start + 500]
            try:
                found |= {r[0] for r in con.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IN ({', '.join('?' * len(chunk))})", chunk)}
            except sqlite3.OperationalError as e:
                if "no such" in str(e):
                    break        # a small test database without this table
                return candidates   # the lookup failed (time limit): hide them all
    return found


def hide_ids(con: sqlite3.Connection, rows: list[list]) -> tuple[list[list], int]:
    """Replace every customer, order or review id inside the rows. Returns the rows and how
    many values were changed."""
    candidates = {m for row in rows for v in row if isinstance(v, str) for m in HEX_ID.findall(v)}
    ids = known_ids(con, candidates) if candidates else set()
    if not ids:
        return rows, 0
    changed = 0

    def hide(value):
        nonlocal changed
        if not isinstance(value, str):
            return value
        new = HEX_ID.sub(lambda m: "#" + hash_id(m.group()) if m.group() in ids else m.group(), value)
        changed += new != value
        return new

    return [[hide(v) for v in row] for row in rows], changed


def run_sql(query: str, db_path: Path = DB_PATH, timeout_s: float = TIMEOUT_S) -> dict:
    """Validate and run one SELECT. Returns at most MAX_ROWS rows, or an error."""
    checked = validate_sql(query)
    if not checked["ok"]:
        return {"error": checked["error"], "message": checked["message"]}
    sql = checked["sql"]

    con = connect_for_queries(db_path, timeout_s)
    try:
        cursor = con.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows = [list(r) for r in cursor.fetchmany(MAX_ROWS)]
        rows, hidden = hide_ids(con, rows)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            return {"error": "TIMEOUT", "message": f"The query took longer than {timeout_s} seconds.", "sql": sql}
        return {"error": "SQL_ERROR", "message": str(e), "sql": sql}
    finally:
        con.close()
    result = {"columns": columns, "rows": rows, "row_count": len(rows), "sql": sql,
              "limited": len(rows) == MAX_ROWS}
    if hidden:
        result["ids_hidden"] = hidden
        result["ids_note"] = "Some values were customer, order or review ids and are shown as '#' + a hash."
    return result

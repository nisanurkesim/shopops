# run_sql: free SQL for the Ops Data Agent, behind three layers (guardrail G3)
# 1. The validator (src/guardrails/sql_validator.py) checks the query before it runs.
# 2. The database is opened read-only (mode=ro), so nothing can be written.
# 3. ATTACH is switched off on the connection (SQLITE_LIMIT_ATTACHED = 0): mode=ro alone
#    does not stop ATTACH from opening or creating another file.
# A query that runs longer than TIMEOUT_S is stopped. SQLite errors (for example a wrong
# column name) are returned to the agent so it can correct the query (G4).
import sqlite3
import time
from pathlib import Path

from config import DB_PATH
from src.guardrails.sql_validator import MAX_ROWS, validate_sql

TIMEOUT_S = 10


def connect_for_queries(db_path: Path = DB_PATH, timeout_s: float = TIMEOUT_S) -> sqlite3.Connection:
    """A read-only connection with ATTACH switched off and a time limit per query."""
    con = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    deadline = time.monotonic() + timeout_s
    # SQLite calls this every 10,000 steps; a non-zero return stops the query
    con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    return con


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
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            return {"error": "TIMEOUT", "message": f"The query took longer than {timeout_s} seconds.", "sql": sql}
        return {"error": "SQL_ERROR", "message": str(e), "sql": sql}
    finally:
        con.close()
    return {"columns": columns, "rows": rows, "row_count": len(rows), "sql": sql,
            "limited": len(rows) == MAX_ROWS}

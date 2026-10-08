# Smoke test: check that the SQLite database was built correctly
import sqlite3
import sys
from pathlib import Path

# Let this script import config.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH, SIMULATED_TODAY

# Expected row counts after loading and applying R0
EXPECTED_ROWS = {
    "orders": 99_421,
    "order_items": 112_649,
    "payments": 103_866,
    "reviews": 99_205,
    "customers": 99_421,
    "sellers": 3_095,
    "products": 32_951,
    "category_translation": 71,
    "return_requests": 0,
}

failures = []


def check(condition, message):
    label = "OK  " if condition else "FAIL"
    print(f"[{label}] {message}")
    if not condition:
        failures.append(message)


def scalar(con, sql, params=()):
    # Run a query that returns a single number
    return con.execute(sql, params).fetchone()[0]


def main():
    if not DB_PATH.exists():
        print("Database not found. Run first: python scripts\\load_sqlite.py")
        sys.exit(1)

    # Open the database in read-only mode: this test must never change data
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)

    # 1) Row counts
    for table, expected in EXPECTED_ROWS.items():
        actual = scalar(con, f"SELECT COUNT(*) FROM {table}")
        check(actual == expected, f"{table}: {actual:,} rows (expected {expected:,})")

    # 2) R0: no order placed on or after SIMULATED_TODAY
    future = scalar(
        con,
        "SELECT COUNT(*) FROM orders WHERE DATE(order_purchase_timestamp) >= DATE(?)",
        (SIMULATED_TODAY,),
    )
    check(future == 0, f"R0: {future} orders on or after {SIMULATED_TODAY} (expected 0)")

    # 3) Every order_id appears only once
    total = scalar(con, "SELECT COUNT(*) FROM orders")
    distinct = scalar(con, "SELECT COUNT(DISTINCT order_id) FROM orders")
    check(total == distinct, f"order_id is unique ({distinct:,} distinct of {total:,})")

    # 4) No order item points to a missing order
    orphans = scalar(
        con,
        "SELECT COUNT(*) FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)",
    )
    check(orphans == 0, f"order_items without an order: {orphans} (expected 0)")

    # 5) Our indexes exist
    n_idx = scalar(con, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")
    check(n_idx == 7, f"indexes: {n_idx} (expected 7)")

    con.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
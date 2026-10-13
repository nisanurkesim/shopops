# Unauthorized access test (guardrail G2, rule R1)
# Picks 10 orders that belong to other customers and asks for them from the demo
# customer's session with every order tool. Each call must answer NOT_FOUND with the
# same message as an order id that does not exist at all.
# Run: python eval/check_access.py
import csv
import sqlite3
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH
from src.returns import NOT_FOUND
from src.tools.orders import Session, check_return_eligibility, get_order_status
from src.tools.return_requests import prepare_return_request

OUT_PATH = Path(__file__).resolve().parent / "results" / "access_test.csv"
DEMO_CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"
MISSING_ORDER = "0" * 32   # an order id that does not exist

# How many foreign orders to take from each status (10 in total)
SAMPLE = [("delivered", 5), ("shipped", 2), ("canceled", 2), ("processing", 1)]

FOREIGN_ORDERS_SQL = """
SELECT o.order_id
FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.order_status = ? AND c.customer_unique_id != ?
ORDER BY o.order_id
LIMIT ?
"""


def pick_foreign_orders(db_path: Path) -> list[tuple[str, str]]:
    con = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    orders = []
    for status, n in SAMPLE:
        rows = con.execute(FOREIGN_ORDERS_SQL, (status, DEMO_CUSTOMER, n)).fetchall()
        orders += [(r[0], status) for r in rows]
    con.close()
    return orders


def ask_all_tools(session: Session, order_id: str, db_path: Path) -> dict:
    """The answer of every order tool for one order id."""
    return {
        "get_order_status": get_order_status(session, order_id, db_path=db_path),
        "check_return_eligibility": check_return_eligibility(session, order_id, "damaged", db_path=db_path),
        "create_return_request": prepare_return_request(session, order_id, "damaged", db_path=db_path)[0],
    }


def main(db_path: Path = DB_PATH):
    session = Session(DEMO_CUSTOMER)
    # Reference answers: what the tools say for an order that does not exist
    reference = ask_all_tools(session, MISSING_ORDER, db_path)

    rows = []
    for order_id, real_status in pick_foreign_orders(db_path):
        answers = ask_all_tools(session, order_id, db_path)
        for tool, answer in answers.items():
            rows.append({
                "order_id": order_id,
                "real_status": real_status,
                "tool": tool,
                "answer_error": answer.get("error", ""),
                "not_found": answer.get("error") == NOT_FOUND,
                "same_as_missing_order": answer == reference[tool],
            })

    OUT_PATH.parent.mkdir(exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # One line per order: did all three tools hide it?
    passed = 0
    for order_id, real_status in dict.fromkeys((r["order_id"], r["real_status"]) for r in rows):
        calls = [r for r in rows if r["order_id"] == order_id]
        ok = all(r["not_found"] and r["same_as_missing_order"] for r in calls)
        passed += ok
        print(f"{'ok  ' if ok else 'FAIL'} {order_id[:8]} (really {real_status}): "
              f"{sum(r['not_found'] for r in calls)}/{len(calls)} tools answered NOT_FOUND")
    total = len(rows) // len(reference)
    print(f"\nNOT_FOUND with the same answer as a missing order: {passed}/{total} "
          f"orders ({100 * passed / total:.0f}%), {len(rows)} tool calls")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
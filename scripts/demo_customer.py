# Print a customer for the CLI demo: one order, delivered in the last 14 days, not late,
# under 500 BRL, not used in the golden set and with no return request yet.
# So "return my last order" works without an order number, and the demo does not
# change any golden set case.
# Usage (PowerShell): $c = python scripts\demo_customer.py; python scripts\chat.py $c
import json
import sqlite3
import sys
from pathlib import Path

# Let this script import config.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH, PROJECT_ROOT, SIMULATED_TODAY

GOLDEN_PATH = PROJECT_ROOT / "eval" / "golden_set.jsonl"

DEMO_SQL = """
SELECT c.customer_unique_id, o.order_id
FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND DATE(o.order_delivered_customer_date) <= :today
  AND julianday(:today) - julianday(DATE(o.order_delivered_customer_date)) BETWEEN 0 AND 14
  AND julianday(DATE(o.order_delivered_customer_date)) - julianday(DATE(o.order_estimated_delivery_date)) < 10
  AND (SELECT SUM(i.price + i.freight_value) FROM order_items AS i WHERE i.order_id = o.order_id) < 500
  AND o.order_id NOT IN (SELECT order_id FROM return_requests)
  AND c.customer_unique_id IN (
      SELECT c2.customer_unique_id
      FROM orders AS o2 JOIN customers AS c2 ON o2.customer_id = c2.customer_id
      GROUP BY c2.customer_unique_id HAVING COUNT(*) = 1)
ORDER BY o.order_id
"""


def main(db_path: Path = DB_PATH):
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    used_orders = {c["order_id"] for c in cases if c.get("order_id")}
    used_customers = {c["session_customer"] for c in cases if c.get("session_customer")}

    con = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    rows = con.execute(DEMO_SQL, {"today": SIMULATED_TODAY}).fetchall()
    con.close()
    for customer, order_id in rows:
        if order_id not in used_orders and customer not in used_customers:
            print(customer)
            return
    raise SystemExit("No customer matches the demo conditions.")


if __name__ == "__main__":
    main()
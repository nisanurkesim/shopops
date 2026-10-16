# Tests for what the tools give the LLM to write (error analysis 4, 5, 6 and 7)
# 4: the return tool says when a parcel in transit is past its estimated date
# 5: a ready short order number (order_ref), so the model does not cut ids itself
# 6: Turkish text next to every code, so codes are not shown to the customer
# 7: after a declined approval the agent is told the summary is gone
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import src.returns as returns
from src.agents.support_agent import SupportAgent
from src.tools.orders import (
    DECISION_TEXT, STATUS_TEXT, Session, check_return_eligibility, get_order_status, list_customer_orders,
)
from src.tools.return_requests import PendingReturn

SCHEMA = """
CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT);
CREATE TABLE orders (
    order_id TEXT, customer_id TEXT, order_status TEXT,
    order_purchase_timestamp TEXT, order_delivered_carrier_date TEXT,
    order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT
);
CREATE TABLE order_items (order_id TEXT, price REAL, freight_value REAL, shipping_limit_date TEXT);
CREATE TABLE payments (order_id TEXT, payment_type TEXT, payment_value REAL);
CREATE TABLE return_requests (order_id TEXT, status TEXT);
"""

DELIVERED = "aaaa1111bbbb2222cccc3333dddd4444"   # delivered 5 days ago
OLD_SHIPPED = "eeee5555ffff6666aaaa7777bbbb8888"  # shipped, estimate long passed
FUTURE = "cccc9999dddd0000eeee1111ffff2222"       # delivery date after SIMULATED_TODAY
LATE_OLD = "dddd3333eeee4444ffff5555aaaa6666"     # delivered 22 days ago, 16 days late
ONTIME_OLD = "ffff7777aaaa8888bbbb9999cccc0000"   # delivered 22 days ago, before the estimate

ORDERS = [
    (DELIVERED, "c1", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
    (OLD_SHIPPED, "c2", "shipped", "2018-06-01 10:00:00", "2018-06-03 09:00:00", None, "2018-06-20 00:00:00"),
    (FUTURE, "c3", "delivered", "2018-08-25 10:00:00", "2018-08-27 09:00:00", "2018-09-05 12:00:00", "2018-09-10 00:00:00"),
    (LATE_OLD, "c4", "delivered", "2018-07-01 10:00:00", "2018-07-03 09:00:00", "2018-08-10 15:00:00", "2018-07-25 00:00:00"),
    (ONTIME_OLD, "c5", "delivered", "2018-08-01 10:00:00", "2018-08-03 09:00:00", "2018-08-10 15:00:00", "2018-08-15 00:00:00"),
]


class ToolTextTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.tmp.name) / "test.db"
        con = sqlite3.connect(cls.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?)", [("c1", "alice"), ("c2", "alice"), ("c3", "alice"), ("c4", "alice"), ("c5", "alice")])
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)",
                        [(o[0], 100.0, 20.0, None) for o in ORDERS])
        con.commit()
        con.close()
        cls.alice = Session("alice")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # --- 5: short order number ---

    def test_order_status_has_order_ref(self):
        result = get_order_status(self.alice, DELIVERED, db_path=self.db)
        self.assertEqual(result["order_ref"], DELIVERED[:8])

    def test_order_list_has_order_ref(self):
        orders = list_customer_orders(self.alice, limit=5, db_path=self.db)["orders"]
        self.assertTrue(all(o["order_ref"] == o["order_id"][:8] for o in orders))

    # --- 6: Turkish text next to codes ---

    def test_status_text(self):
        result = get_order_status(self.alice, DELIVERED, db_path=self.db)
        self.assertEqual(result["status_text"], STATUS_TEXT["delivered"])

    def test_decision_and_approval_text(self):
        result = check_return_eligibility(self.alice, DELIVERED, "damaged", db_path=self.db)
        self.assertEqual(result["decision_text"], DECISION_TEXT["ELIGIBLE"])
        self.assertEqual(result["approval_text"], "Temsilci onayı bekleyecek")

    def test_every_decision_code_has_a_text(self):
        codes = [returns.ELIGIBLE, returns.NOT_ELIGIBLE_WINDOW, returns.IN_TRANSIT, returns.NEEDS_HUMAN,
                 returns.NOT_DELIVERED_CANCELLABLE, returns.ALREADY_CLOSED, returns.DUPLICATE_REQUEST]
        self.assertEqual([c for c in codes if c not in DECISION_TEXT], [])

    def test_freight_only_has_its_own_text(self):
        # Error analysis 9: "Iade suresi gecmis" alone hid the freight refund (S15)
        result = check_return_eligibility(self.alice, LATE_OLD, "late", db_path=self.db)
        self.assertEqual(result["code"], "NOT_ELIGIBLE_WINDOW")
        self.assertEqual(result["refund_amount"], 20.0)
        self.assertIn("kargo ücreti", result["decision_text"])

    def test_window_passed_without_freight_keeps_the_plain_text(self):
        result = check_return_eligibility(self.alice, ONTIME_OLD, "changed_mind", db_path=self.db)
        self.assertEqual(result["code"], "NOT_ELIGIBLE_WINDOW")
        self.assertEqual(result["refund_amount"], 0.0)
        self.assertEqual(result["decision_text"], DECISION_TEXT["NOT_ELIGIBLE_WINDOW"])

    # --- 4: lost parcel flag in the return tool ---

    def test_old_shipped_order_is_flagged_in_return_check(self):
        result = check_return_eligibility(self.alice, OLD_SHIPPED, "changed_mind", db_path=self.db)
        self.assertEqual(result["code"], "IN_TRANSIT")
        self.assertTrue(result["past_estimated_date"])

    def test_future_delivery_is_not_flagged(self):
        result = check_return_eligibility(self.alice, FUTURE, "changed_mind", db_path=self.db)
        self.assertEqual(result["code"], "IN_TRANSIT")
        self.assertFalse(result["past_estimated_date"])

    # --- 7: note after a declined approval ---

    def test_decline_note_asks_for_a_new_summary(self):
        agent = SupportAgent(self.alice, client=SimpleNamespace(models=None))
        agent.pending = PendingReturn("token", "alice", DELIVERED, "damaged", 120.0, "PENDING_REVIEW")
        agent.confirm_return(False)
        self.assertIn("no longer on screen", agent.interface_note)
        self.assertIn("create_return_request", agent.interface_note)

    def test_return_summary_has_ref_and_text(self):
        pending = PendingReturn("token", "alice", DELIVERED, "damaged", 120.0, "PENDING_SENIOR")
        summary = pending.summary()
        self.assertEqual(summary["order_ref"], DELIVERED[:8])
        self.assertEqual(summary["approval_text"], "Kıdemli temsilci onayı bekleyecek")


if __name__ == "__main__":
    unittest.main()
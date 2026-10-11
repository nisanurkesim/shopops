# Tests for the order tools (src/tools/orders.py)
# They use a small temporary database, so they do not need the Olist data.
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.tools.orders import (
    NOT_FOUND_MESSAGE, Session,
    check_return_eligibility, get_order_status, list_customer_orders,
)

SCHEMA = """
CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT);
CREATE TABLE orders (
    order_id TEXT, customer_id TEXT, order_status TEXT,
    order_purchase_timestamp TEXT, order_approved_at TEXT,
    order_delivered_carrier_date TEXT, order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT
);
CREATE TABLE order_items (order_id TEXT, price REAL, freight_value REAL, shipping_limit_date TEXT);
CREATE TABLE payments (order_id TEXT, payment_type TEXT, payment_value REAL);
CREATE TABLE return_requests (order_id TEXT, status TEXT);
"""

# In Olist every order has its own customer_id; customer_unique_id is the real person
CUSTOMERS = [
    ("cid-a1", "alice"), ("cid-a2", "alice"), ("cid-a3", "alice"), ("cid-a4", "alice"),
    ("cid-b1", "bob"),
]

ORDERS = [
    # order_id, customer_id, status, purchased, carrier, delivered, estimated
    ("A1", "cid-a1", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
    ("A2", "cid-a2", "shipped",   "2018-06-01 10:00:00", "2018-06-03 09:00:00", None,                  "2018-06-20 00:00:00"),
    ("A3", "cid-a3", "delivered", "2018-08-25 10:00:00", "2018-08-27 09:00:00", "2018-09-05 12:00:00", "2018-09-10 00:00:00"),
    ("A4", "cid-a4", "delivered", "2018-08-01 10:00:00", "2018-08-03 09:00:00", "2018-08-20 12:00:00", "2018-08-25 00:00:00"),
    ("B1", "cid-b1", "delivered", "2018-08-12 10:00:00", "2018-08-14 09:00:00", "2018-08-28 15:00:00", "2018-09-02 00:00:00"),
]

ITEMS = [
    ("A1", 100.0, 20.0, "2018-08-15 00:00:00"),
    ("A2", 50.0, 10.0, "2018-06-05 00:00:00"),
    ("A3", 70.0, 15.0, "2018-08-28 00:00:00"),
    ("A4", 40.0, 8.0, "2018-08-05 00:00:00"),
    ("B1", 300.0, 25.0, "2018-08-15 00:00:00"),
]

PAYMENTS = [("A1", "credit_card", 120.0), ("B1", "boleto", 325.0)]
REQUESTS = [("A4", "PENDING_REVIEW")]


class OrderToolsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.tmp.name) / "test.db"
        con = sqlite3.connect(cls.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?)", CUSTOMERS)
        con.executemany(
            "INSERT INTO orders (order_id, customer_id, order_status, order_purchase_timestamp, "
            "order_delivered_carrier_date, order_delivered_customer_date, order_estimated_delivery_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", ITEMS)
        con.executemany("INSERT INTO payments VALUES (?, ?, ?)", PAYMENTS)
        con.executemany("INSERT INTO return_requests VALUES (?, ?)", REQUESTS)
        con.commit()
        con.close()
        cls.alice = Session("alice")
        cls.bob = Session("bob")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # --- get_order_status ---

    def test_own_order(self):
        r = get_order_status(self.alice, "A1", db_path=self.db)
        self.assertEqual(r["status"], "delivered")
        self.assertEqual(r["delivered_date"], "2018-08-27")
        self.assertEqual((r["items_total"], r["freight_total"]), (100.0, 20.0))

    def test_other_customers_order_looks_like_missing_order(self):
        foreign = get_order_status(self.alice, "B1", db_path=self.db)
        missing = get_order_status(self.alice, "does-not-exist", db_path=self.db)
        self.assertEqual(foreign, missing)
        self.assertEqual(foreign["message"], NOT_FOUND_MESSAGE)

    def test_delivery_after_today_is_shown_as_shipped(self):
        r = get_order_status(self.alice, "A3", db_path=self.db)
        self.assertEqual(r["status"], "shipped")
        self.assertIsNone(r["delivered_date"])
        self.assertFalse(r["past_estimated_date"])   # estimate 2018-09-10 is still ahead

    def test_old_shipped_order_is_flagged(self):
        r = get_order_status(self.alice, "A2", db_path=self.db)
        self.assertEqual(r["status"], "shipped")
        self.assertTrue(r["past_estimated_date"])

    # --- list_customer_orders ---

    def test_list_newest_first(self):
        r = list_customer_orders(self.alice, limit=10, db_path=self.db)
        self.assertEqual([o["order_id"] for o in r["orders"]], ["A3", "A1", "A4", "A2"])
        self.assertEqual(r["total_orders"], 4)

    def test_list_limit(self):
        r = list_customer_orders(self.alice, limit=2, db_path=self.db)
        self.assertEqual(len(r["orders"]), 2)

    def test_list_status_filter_uses_customer_view(self):
        r = list_customer_orders(self.alice, status="shipped", db_path=self.db)
        self.assertEqual([o["order_id"] for o in r["orders"]], ["A3", "A2"])

    def test_list_only_own_orders(self):
        r = list_customer_orders(self.bob, db_path=self.db)
        self.assertEqual([o["order_id"] for o in r["orders"]], ["B1"])

    # --- check_return_eligibility ---

    def test_eligibility_own_order(self):
        r = check_return_eligibility(self.alice, "A1", "damaged", db_path=self.db)
        self.assertEqual((r["code"], r["rule"], r["refund_amount"]), ("ELIGIBLE", "R7", 120.0))

    def test_eligibility_other_customers_order(self):
        foreign = check_return_eligibility(self.alice, "B1", "damaged", db_path=self.db)
        missing = check_return_eligibility(self.alice, "nope", "damaged", db_path=self.db)
        self.assertEqual(foreign, missing)
        self.assertNotIn("rule", foreign)   # do not reveal R0 / R1

    def test_eligibility_existing_request(self):
        r = check_return_eligibility(self.alice, "A4", "changed_mind", db_path=self.db)
        self.assertEqual(r["code"], "DUPLICATE_REQUEST")

    def test_eligibility_future_delivery(self):
        r = check_return_eligibility(self.alice, "A3", "damaged", db_path=self.db)
        self.assertEqual(r["code"], "IN_TRANSIT")

    def test_invalid_reason(self):
        r = check_return_eligibility(self.alice, "A1", "too_expensive", db_path=self.db)
        self.assertEqual(r["error"], "INVALID_REASON")


if __name__ == "__main__":
    unittest.main()
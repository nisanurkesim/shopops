# Tests for return requests behind human approval (src/tools/return_requests.py)
# Brief, roadmap step 7: without approval the table stays empty; with approval
# exactly one row with the R10 status is written.
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.tools.orders import Session
from src.tools.return_requests import (
    APPROVAL_REQUIRED, create_return_request, prepare_return_request,
)

SCHEMA = """
CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT);
CREATE TABLE orders (
    order_id TEXT, customer_id TEXT, order_status TEXT,
    order_purchase_timestamp TEXT, order_delivered_carrier_date TEXT,
    order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT
);
CREATE TABLE order_items (order_id TEXT, price REAL, freight_value REAL, shipping_limit_date TEXT);
CREATE TABLE payments (order_id TEXT, payment_type TEXT, payment_value REAL);
CREATE TABLE return_requests (
    return_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('changed_mind', 'damaged', 'wrong_item', 'late')),
    refund_amount REAL NOT NULL CHECK (refund_amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING_REVIEW', 'PENDING_SENIOR', 'APPROVED', 'REJECTED')),
    created_at TEXT NOT NULL
);
"""

CUSTOMERS = [("cid-1", "alice"), ("cid-2", "alice"), ("cid-3", "alice"), ("cid-4", "bob")]
ORDERS = [
    # small order, delivered 5 days ago
    ("SMALL", "cid-1", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
    # expensive order, delivered 5 days ago
    ("BIG", "cid-2", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
    # delivered 40 days ago: nothing to refund
    ("OLD", "cid-3", "delivered", "2018-07-01 10:00:00", "2018-07-03 09:00:00", "2018-07-23 15:00:00", "2018-07-30 00:00:00"),
    ("BOBS", "cid-4", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
]
ITEMS = [("SMALL", 100.0, 20.0, None), ("BIG", 600.0, 30.0, None),
         ("OLD", 50.0, 10.0, None), ("BOBS", 80.0, 10.0, None)]


class ReturnRequestTest(unittest.TestCase):

    def setUp(self):
        # A fresh database for every test, so row counts start from zero
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?)", CUSTOMERS)
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", ITEMS)
        con.commit()
        con.close()
        self.alice = Session("alice")

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        con = sqlite3.connect(self.db)
        rows = con.execute("SELECT order_id, reason, refund_amount, status FROM return_requests").fetchall()
        con.close()
        return rows

    def test_prepare_writes_nothing(self):
        result, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        self.assertEqual(result["status"], APPROVAL_REQUIRED)
        self.assertIsNotNone(pending)
        self.assertEqual(self.rows(), [])

    def test_summary_does_not_contain_the_token(self):
        result, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        self.assertNotIn("token", result)
        self.assertNotIn(pending.token, str(result))

    def test_wrong_token_writes_nothing(self):
        _, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        result = create_return_request(self.alice, pending, "onaylandi", db_path=self.db)
        self.assertEqual(result["error"], APPROVAL_REQUIRED)
        self.assertEqual(self.rows(), [])

    def test_no_pending_request_writes_nothing(self):
        result = create_return_request(self.alice, None, "anything", db_path=self.db)
        self.assertEqual(result["error"], APPROVAL_REQUIRED)
        self.assertEqual(self.rows(), [])

    def test_approved_writes_one_row_with_r10_status(self):
        _, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        result = create_return_request(self.alice, pending, pending.token, db_path=self.db)
        self.assertIn("return_request_id", result)
        self.assertEqual(self.rows(), [("SMALL", "damaged", 120.0, "PENDING_REVIEW")])

    def test_expensive_request_needs_senior(self):
        _, pending = prepare_return_request(self.alice, "BIG", "damaged", db_path=self.db)
        create_return_request(self.alice, pending, pending.token, db_path=self.db)
        self.assertEqual(self.rows(), [("BIG", "damaged", 630.0, "PENDING_SENIOR")])

    def test_same_approval_cannot_be_used_twice(self):
        _, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        create_return_request(self.alice, pending, pending.token, db_path=self.db)
        second = create_return_request(self.alice, pending, pending.token, db_path=self.db)
        self.assertEqual(second["error"], "NOT_ELIGIBLE")   # R11: a request already exists
        self.assertEqual(len(self.rows()), 1)

    def test_not_eligible_order_is_not_prepared(self):
        result, pending = prepare_return_request(self.alice, "OLD", "changed_mind", db_path=self.db)
        self.assertEqual(result["error"], "NOT_ELIGIBLE")
        self.assertIsNone(pending)

    def test_other_customers_order_is_not_found(self):
        result, pending = prepare_return_request(self.alice, "BOBS", "damaged", db_path=self.db)
        self.assertEqual(result["error"], "NOT_FOUND")
        self.assertIsNone(pending)

    def test_approval_belongs_to_one_customer(self):
        _, pending = prepare_return_request(self.alice, "SMALL", "damaged", db_path=self.db)
        result = create_return_request(Session("bob"), pending, pending.token, db_path=self.db)
        self.assertEqual(result["error"], APPROVAL_REQUIRED)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
# Tests for the semantic layer and run_metric (brief section 5.4)
# A small database where the right answer of every tricky case is known: calendar days,
# deliveries after SIMULATED_TODAY, orders with two categories, canceled orders in GMV,
# orders with two reviews, and a filter value that tries SQL injection.
import sqlite3
import tempfile
import unittest
from pathlib import Path

from config import DB_PATH
from src.tools.metrics import list_metrics, load_semantic_layer, run_metric

SCHEMA = """
CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT, customer_state TEXT);
CREATE TABLE orders (
    order_id TEXT, customer_id TEXT, order_status TEXT, order_purchase_timestamp TEXT,
    order_approved_at TEXT, order_delivered_carrier_date TEXT,
    order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT
);
CREATE TABLE order_items (order_id TEXT, order_item_id INTEGER, product_id TEXT, seller_id TEXT,
                          shipping_limit_date TEXT, price REAL, freight_value REAL);
CREATE TABLE products (product_id TEXT, product_category_name TEXT);
CREATE TABLE category_translation (product_category_name TEXT, product_category_name_english TEXT);
CREATE TABLE sellers (seller_id TEXT, seller_state TEXT);
CREATE TABLE reviews (review_id TEXT, order_id TEXT, review_score INTEGER);
"""

# order, customer, status, purchased, carrier, delivered, estimated
ORDERS = [
    # delivered in the afternoon of the estimated day: on time (calendar days)
    ("ONTIME", "c1", "delivered", "2018-08-01 10:00:00", "2018-08-02 09:00:00", "2018-08-10 18:00:00", "2018-08-10 00:00:00"),
    # delivered one day after the estimate: late
    ("LATE", "c2", "delivered", "2018-08-01 10:00:00", "2018-08-05 09:00:00", "2018-08-11 09:00:00", "2018-08-10 00:00:00"),
    # delivered after SIMULATED_TODAY: not delivered yet, left out of delivery metrics
    ("FUTURE", "c1", "delivered", "2018-08-20 10:00:00", "2018-08-22 09:00:00", "2018-09-05 12:00:00", "2018-09-01 00:00:00"),
    ("CANCELED", "c2", "canceled", "2018-08-03 10:00:00", None, None, "2018-08-20 00:00:00"),
]
ITEMS = [
    ("ONTIME", 1, "chair", "s1", "2018-08-03 00:00:00", 100.0, 10.0),
    ("ONTIME", 2, "lamp", "s1", "2018-08-03 00:00:00", 50.0, 5.0),     # second category
    ("LATE", 1, "chair", "s2", "2018-08-03 00:00:00", 100.0, 10.0),    # shipped after the limit
    ("LATE", 2, "chair", "s2", "2018-08-03 00:00:00", 100.0, 10.0),    # same category twice
    ("FUTURE", 1, "lamp", "s1", "2018-08-25 00:00:00", 40.0, 4.0),
    ("CANCELED", 1, "chair", "s1", "2018-08-05 00:00:00", 999.0, 9.0),
]


class MetricsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.tmp.name) / "test.db"
        con = sqlite3.connect(cls.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?, ?)",
                        [("c1", "alice", "SP"), ("c2", "bob", "RJ")])
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, NULL, ?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)", ITEMS)
        con.executemany("INSERT INTO products VALUES (?, ?)", [("chair", "moveis"), ("lamp", "luz")])
        con.executemany("INSERT INTO category_translation VALUES (?, ?)", [("moveis", "furniture")])
        con.executemany("INSERT INTO sellers VALUES (?, ?)", [("s1", "SP"), ("s2", "MG")])
        con.executemany("INSERT INTO reviews VALUES (?, ?, ?)",
                        [("r1", "ONTIME", 5), ("r2", "LATE", 1), ("r3", "LATE", 3)])
        con.commit()
        con.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def value(self, name, filters=None, group_by=None):
        result = run_metric(name, filters, group_by, db_path=self.db)
        self.assertNotIn("error", result)
        return result

    # --- the semantic layer itself ---

    def test_at_least_eight_metrics_with_caveats(self):
        metrics = list_metrics()["metrics"]
        self.assertGreaterEqual(len(metrics), 8)
        layer = load_semantic_layer()
        for name in layer["metrics"]:
            self.assertTrue(layer["metrics"][name]["caveat"], name)

    def test_every_metric_and_dimension_runs(self):
        # Catches a typo in any SQL part of the YAML
        layer = load_semantic_layer()
        for name, metric in layer["metrics"].items():
            for dim in metric["dimensions"]:
                result = run_metric(name, group_by=[dim], db_path=self.db)
                self.assertNotIn("error", result, f"{name} by {dim}")

    # --- definitions ---

    def test_late_delivery_uses_calendar_days_and_simulated_today(self):
        result = self.value("late_delivery_rate")
        # ONTIME is on time (same day), LATE is late, FUTURE is not delivered yet
        self.assertEqual(result["rows"], [[0.5, 2]])

    def test_gmv_leaves_out_canceled_orders_and_freight(self):
        result = self.value("gmv")
        self.assertEqual(result["rows"][0][0], 390.0)   # 150 + 200 + 40, no freight, no 999

    def test_order_with_two_categories_counts_once_in_each(self):
        result = self.value("order_count", group_by=["product_category_en"])
        rows = {r[0]: r[1] for r in result["rows"]}
        # furniture: ONTIME, LATE (two chairs, counted once), CANCELED; luz has no translation
        self.assertEqual(rows, {"furniture": 3, "luz": 2})

    def test_review_score_is_averaged_per_order_first(self):
        result = self.value("avg_review_score")
        self.assertEqual(result["rows"][0][0], 3.5)   # (5 + (1+3)/2) / 2, not (5+1+3)/3

    def test_seller_late_shipping(self):
        result = self.value("seller_late_shipping_rate")
        # ONTIME shipped 08-02 (limit 08-03): on time; LATE shipped 08-05: late; FUTURE: on time
        self.assertEqual(result["rows"], [[0.3333, 3]])

    def test_filter_and_group_by(self):
        result = self.value("late_delivery_rate", {"customer_state": "RJ"})
        self.assertEqual(result["rows"], [[1.0, 1]])
        grouped = self.value("cancel_rate", group_by=["customer_state"])
        self.assertEqual(grouped["rows"], [["RJ", 0.5, 2], ["SP", 0.0, 2]])

    def test_threshold_sort_and_top_n(self):
        # "Categories with at least 3 orders, highest order count first, top 1"
        result = self.value("order_count", group_by=["product_category_en"])
        self.assertEqual(len(result["rows"]), 2)
        top = run_metric("order_count", group_by=["product_category_en"], min_n=3, sort="desc", limit=1,
                         db_path=self.db)
        self.assertEqual(top["rows"], [["furniture", 3, 3]])
        self.assertIn("HAVING", top["sql"])
        lowest = run_metric("cancel_rate", group_by=["customer_state"], sort="asc", limit=1, db_path=self.db)
        self.assertEqual(lowest["rows"], [["SP", 0.0, 2]])

    def test_threshold_options_are_checked(self):
        self.assertEqual(run_metric("gmv", min_n=10, db_path=self.db)["error"], "NEEDS_GROUP_BY")
        self.assertEqual(run_metric("gmv", group_by=["customer_state"], sort="up", db_path=self.db)["error"],
                         "INVALID_SORT")
        self.assertEqual(run_metric("gmv", group_by=["customer_state"], limit=0, db_path=self.db)["error"],
                         "INVALID_NUMBER")
        self.assertEqual(run_metric("gmv", group_by=["customer_state"], min_n="x", db_path=self.db)["error"],
                         "INVALID_NUMBER")

    def test_result_has_sql_and_caveat(self):
        result = self.value("gmv")
        self.assertIn("SELECT", result["sql"])
        self.assertIn("GMV", result["caveat"])

    # --- safety ---

    def test_filter_value_is_a_parameter_not_sql(self):
        result = self.value("order_count", {"customer_state": "SP'; DROP TABLE orders; --"})
        self.assertEqual(result["rows"][0][0], 0)
        self.assertNotIn("DROP", result["sql"])
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 4)
        con.close()

    def test_unknown_names_are_refused(self):
        self.assertEqual(run_metric("profit", db_path=self.db)["error"], "UNKNOWN_METRIC")
        self.assertEqual(run_metric("gmv", group_by=["customer_city"], db_path=self.db)["error"],
                         "UNKNOWN_DIMENSION")
        self.assertEqual(run_metric("gmv", {"o.order_status": "x"}, db_path=self.db)["error"],
                         "UNKNOWN_DIMENSION")
        too_many = ["customer_state", "purchase_month", "seller_state"]
        self.assertEqual(run_metric("gmv", group_by=too_many, db_path=self.db)["error"], "TOO_MANY_GROUPS")


@unittest.skipUnless(DB_PATH.exists(), "database not built: run python scripts/load_sqlite.py")
class BriefValuesTest(unittest.TestCase):
    """The control values the brief gives for the real database (section 5.4)."""

    def test_late_delivery_rate(self):
        self.assertEqual(run_metric("late_delivery_rate")["rows"], [[0.0672, 96417]])

    def test_avg_delivery_days(self):
        self.assertEqual(run_metric("avg_delivery_days")["rows"], [[12.54, 96417]])


if __name__ == "__main__":
    unittest.main()

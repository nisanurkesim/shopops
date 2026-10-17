# Tests for the demo sample (scripts/load_sqlite.py: choose_customers, apply_sample)
# A tiny hand-made database: no download, runs in a moment.
import sqlite3
import unittest

from scripts.load_sqlite import apply_sample, choose_customers

# U1 is one person with two orders. In Olist every order has its own customer_id,
# so U1 has two customer_id values (c1a, c1b).
CUSTOMERS = [("c1a", "U1"), ("c1b", "U1"), ("c2", "U2"), ("c3", "U3")]
ORDERS = [("o1", "c1a"), ("o2", "c1b"), ("o3", "c2"), ("o4", "c3")]
ORDER_ROWS = ["o1", "o2", "o3", "o4"]   # one row per order in each child table


def make_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT)")
    con.execute("CREATE TABLE orders (order_id TEXT, customer_id TEXT)")
    for table in ["order_items", "payments", "reviews"]:
        con.execute(f"CREATE TABLE {table} (order_id TEXT)")
        con.executemany(f"INSERT INTO {table} VALUES (?)", [(o,) for o in ORDER_ROWS])
    con.execute("CREATE TABLE products (product_id TEXT)")
    con.execute("INSERT INTO products VALUES ('p1')")
    con.executemany("INSERT INTO customers VALUES (?, ?)", CUSTOMERS)
    con.executemany("INSERT INTO orders VALUES (?, ?)", ORDERS)
    return con


def column(con, sql) -> set:
    return {r[0] for r in con.execute(sql)}


class TestApplySample(unittest.TestCase):

    def setUp(self):
        self.con = make_db()
        apply_sample(self.con, {"U1", "U3"})   # U2 is not kept

    def test_only_kept_customers_remain(self):
        self.assertEqual(column(self.con, "SELECT customer_unique_id FROM customers"), {"U1", "U3"})

    def test_kept_customer_keeps_all_orders(self):
        # U1's two orders have two different customer_id values; both must stay
        self.assertEqual(column(self.con, "SELECT order_id FROM orders"), {"o1", "o2", "o4"})

    def test_child_tables_follow_the_orders(self):
        for table in ["order_items", "payments", "reviews"]:
            with self.subTest(table=table):
                self.assertEqual(column(self.con, f"SELECT order_id FROM {table}"), {"o1", "o2", "o4"})

    def test_reference_tables_stay_whole(self):
        self.assertEqual(column(self.con, "SELECT product_id FROM products"), {"p1"})

    def test_temporary_table_is_removed(self):
        names = column(self.con, "SELECT name FROM sqlite_temp_master")
        self.assertNotIn("keep_customers", names)


class TestChooseCustomers(unittest.TestCase):

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT)")
        self.con.executemany("INSERT INTO customers VALUES (?, ?)",
                             [(f"c{i}", f"U{i:03}") for i in range(100)])

    def test_same_seed_same_sample(self):
        first = choose_customers(self.con, 0.3, 42, [])
        second = choose_customers(self.con, 0.3, 42, [])
        self.assertEqual(first, second)

    def test_share_of_customers(self):
        self.assertEqual(len(choose_customers(self.con, 0.3, 42, [])), 30)

    def test_demo_customers_are_always_kept(self):
        self.assertTrue({"U000", "U099"} <= choose_customers(self.con, 0.3, 42, ["U000", "U099"]))


if __name__ == "__main__":
    unittest.main()

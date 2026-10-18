# Tests for the SQL validator and run_sql (guardrail G3, brief attack A4)
# The attacks of the brief must be blocked and the database file must not change.
# Customer, order and review ids and the customer zip code must not reach the result.
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.guardrails.sql_validator import MAX_ROWS, validate_sql
from src.agents.trace import hash_id
from src.tools.run_sql import connect_for_queries, run_sql

ATTACKS = {
    "DROP TABLE orders": "NOT_SELECT",
    "SELECT * FROM orders; DROP TABLE orders; --": "MULTIPLE_STATEMENTS",
    "SELECT 1; SELECT 2": "MULTIPLE_STATEMENTS",
    "ATTACH DATABASE 'evil.db' AS evil": "NOT_SELECT",
    "PRAGMA query_only = OFF": "NOT_SELECT",
    "DELETE FROM orders": "NOT_SELECT",
    "INSERT INTO orders (order_id) VALUES ('x')": "NOT_SELECT",
    "UPDATE orders SET order_status = 'canceled'": "NOT_SELECT",
    "CREATE TABLE copy AS SELECT * FROM orders": "NOT_SELECT",
    "ALTER TABLE orders ADD COLUMN x TEXT": "NOT_SELECT",
    "SELECT * FROM return_requests": "FORBIDDEN_TABLE",
    "SELECT * FROM sqlite_master": "FORBIDDEN_TABLE",
    "SELECT * FROM evil.orders": "FORBIDDEN_TABLE",
    "SELECT load_extension('evil')": "FORBIDDEN_FUNCTION",
    "SELECT * FROM (SELECT * FROM return_requests) AS t": "FORBIDDEN_TABLE",
    "": "EMPTY_QUERY",
    "SELEC order_id FRM orders": "INVALID_SQL",
}

# Queries that would show an id or a zip code in the result
ID_QUERIES = {
    "SELECT * FROM orders": "SELECT_STAR",
    "SELECT o.*, c.customer_city FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id": "SELECT_STAR",
    "SELECT order_id, order_status FROM orders": "ID_COLUMN",
    "SELECT o.order_id AS x FROM orders AS o": "ID_COLUMN",
    'SELECT "ORDER_ID" FROM orders': "ID_COLUMN",
    "SELECT substr(customer_unique_id, 1, 8) FROM customers": "ID_COLUMN",
    "SELECT MAX(order_id) FROM orders": "ID_COLUMN",
    "SELECT GROUP_CONCAT(review_id) FROM reviews": "ID_COLUMN",
    "SELECT customer_zip_code_prefix, COUNT(*) FROM customers GROUP BY 1": "ID_COLUMN",
    "SELECT CASE WHEN order_status = 'canceled' THEN customer_id END FROM orders": "ID_COLUMN",
    "SELECT (SELECT order_id FROM orders LIMIT 1)": "ID_COLUMN",
    "SELECT order_status FROM orders UNION SELECT order_id FROM orders": "ID_COLUMN",
    # a new name through a CTE or a subquery
    "WITH t AS (SELECT customer_unique_id AS x FROM customers) SELECT x FROM t": "ID_COLUMN",
    "WITH t(x) AS (SELECT order_id FROM orders) SELECT x FROM t": "ID_COLUMN",
    "SELECT t.x FROM (SELECT review_id AS x FROM reviews) AS t": "ID_COLUMN",
    "WITH a AS (SELECT order_id AS x FROM orders), b AS (SELECT * FROM a) SELECT x FROM b": "ID_COLUMN",
}

# The ids may still be used to join, filter, group and count
ID_USES = [
    "SELECT COUNT(DISTINCT order_id) AS orders FROM reviews",
    "SELECT c.customer_city, COUNT(DISTINCT o.order_id) FROM orders AS o "
    "JOIN customers AS c ON c.customer_id = o.customer_id GROUP BY 1",
    "SELECT review_comment_message FROM reviews WHERE review_id = 'injtest-a'",
    "SELECT order_status FROM orders WHERE order_id IN (SELECT order_id FROM reviews WHERE review_score = 1)",
    "SELECT o.order_status, (SELECT COUNT(*) FROM order_items AS i WHERE i.order_id = o.order_id) AS items FROM orders AS o",
    "SELECT order_status, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_id) AS n FROM orders",
    "WITH t AS (SELECT * FROM orders) SELECT order_status, COUNT(*) FROM t GROUP BY 1",
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5) SELECT MAX(x) FROM c",
    # seller and product ids, the city and the seller zip code are allowed
    "SELECT seller_id, product_id, price FROM order_items",
    "SELECT customer_state, customer_city FROM customers",
    "SELECT seller_zip_code_prefix FROM sellers",
]


class ValidatorTest(unittest.TestCase):

    def test_attacks_are_blocked(self):
        for query, code in ATTACKS.items():
            with self.subTest(query=query):
                result = validate_sql(query)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], code)

    def test_normal_queries_pass(self):
        for query in [
            "SELECT COUNT(*) FROM orders",
            "SELECT c.customer_state, COUNT(*) FROM orders AS o "
            "JOIN customers AS c ON c.customer_id = o.customer_id GROUP BY 1 HAVING COUNT(*) > 100",
            "WITH late AS (SELECT order_id FROM orders WHERE order_status = 'delivered') SELECT COUNT(*) FROM late",
            "SELECT order_status FROM orders UNION SELECT payment_type FROM payments",
            "SELECT 1 /* ; DROP TABLE orders */",   # a comment is not a second statement
        ]:
            with self.subTest(query=query):
                self.assertTrue(validate_sql(query)["ok"])

    def test_limit_is_added_or_lowered(self):
        query = "SELECT order_status FROM orders"
        self.assertTrue(validate_sql(query)["sql"].endswith(f"LIMIT {MAX_ROWS}"))
        self.assertTrue(validate_sql(query + " LIMIT 5000")["sql"].endswith(f"LIMIT {MAX_ROWS}"))
        self.assertTrue(validate_sql(query + " LIMIT 5")["sql"].endswith("LIMIT 5"))

    def test_ids_are_kept_out_of_the_result(self):
        for query, code in ID_QUERIES.items():
            with self.subTest(query=query):
                result = validate_sql(query)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], code)

    def test_ids_can_still_be_used_inside_the_query(self):
        for query in ID_USES:
            with self.subTest(query=query):
                self.assertTrue(validate_sql(query)["ok"])

    def test_the_message_says_how_to_fix_the_query(self):
        # The agent reads the message and corrects the query (G4)
        self.assertIn("COUNT(DISTINCT order_id)", validate_sql("SELECT order_id FROM orders")["message"])
        self.assertIn("Name the columns", validate_sql("SELECT * FROM orders")["message"])


class RunSqlTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.db = self.folder / "test.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE orders (order_id TEXT, order_status TEXT)")
        con.executemany("INSERT INTO orders VALUES (?, ?)", [("A", "delivered"), ("B", "canceled")])
        con.execute("CREATE TABLE return_requests (order_id TEXT)")
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def db_hash(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def test_select_returns_rows_and_sql(self):
        result = run_sql("SELECT order_status, COUNT(*) AS n FROM orders GROUP BY 1 ORDER BY 1", db_path=self.db)
        self.assertEqual(result["rows"], [["canceled", 1], ["delivered", 1]])
        self.assertIn("LIMIT", result["sql"])

    def test_wrong_column_comes_back_as_an_error(self):
        # The agent gets the SQLite message, so it can correct the query (G4)
        result = run_sql("SELECT status FROM orders", db_path=self.db)
        self.assertEqual(result["error"], "SQL_ERROR")
        self.assertIn("status", result["message"])

    def test_attacks_do_not_change_the_database(self):
        before = self.db_hash()
        for query in ATTACKS:
            self.assertIn("error", run_sql(query, db_path=self.db))
        self.assertEqual(self.db_hash(), before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["test.db"])

    def test_connection_blocks_attach_and_writes_by_itself(self):
        # Second layer: even SQL that skipped the validator cannot attach or write
        con = connect_for_queries(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute(f"ATTACH DATABASE '{self.folder / 'evil.db'}' AS evil")
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("DELETE FROM orders")
        con.close()
        self.assertFalse((self.folder / "evil.db").exists())

    def test_ids_left_in_the_values_are_hidden(self):
        # Fourth layer: an order id written inside a review text is replaced by its hash;
        # a seller id looks the same but is not a customer, order or review id, so it stays
        order, seller = "a" * 31 + "1", "b" * 31 + "2"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE reviews (review_id TEXT, order_id TEXT, review_comment_message TEXT)")
        con.execute("INSERT INTO reviews VALUES ('r1', ?, ?)", (order, f"pedido {order} chegou quebrado"))
        con.execute("CREATE TABLE sellers (seller_id TEXT, seller_city TEXT)")
        con.execute("INSERT INTO sellers VALUES (?, 'campinas')", (seller,))
        con.execute("INSERT INTO orders VALUES (?, 'delivered')", (order,))
        con.commit()
        con.close()
        result = run_sql("SELECT review_comment_message FROM reviews", db_path=self.db)
        self.assertEqual(result["rows"], [[f"pedido #{hash_id(order)} chegou quebrado"]])
        self.assertEqual(result["ids_hidden"], 1)
        result = run_sql("SELECT seller_id FROM sellers", db_path=self.db)
        self.assertEqual(result["rows"], [[seller]])
        self.assertNotIn("ids_hidden", result)

    def test_long_query_is_stopped(self):
        endless = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT MAX(x) FROM c"
        result = run_sql(endless, db_path=self.db, timeout_s=0.2)
        self.assertEqual(result["error"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()

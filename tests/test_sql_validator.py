# Tests for the SQL validator and run_sql (guardrail G3, brief attack A4)
# The attacks of the brief must be blocked and the database file must not change.
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.guardrails.sql_validator import MAX_ROWS, validate_sql
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
            "SELECT order_id FROM orders UNION SELECT order_id FROM order_items",
            "SELECT 1 /* ; DROP TABLE orders */",   # a comment is not a second statement
        ]:
            with self.subTest(query=query):
                self.assertTrue(validate_sql(query)["ok"])

    def test_limit_is_added_or_lowered(self):
        self.assertTrue(validate_sql("SELECT * FROM orders")["sql"].endswith(f"LIMIT {MAX_ROWS}"))
        self.assertTrue(validate_sql("SELECT * FROM orders LIMIT 5000")["sql"].endswith(f"LIMIT {MAX_ROWS}"))
        self.assertTrue(validate_sql("SELECT * FROM orders LIMIT 5")["sql"].endswith("LIMIT 5"))


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

    def test_long_query_is_stopped(self):
        endless = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT MAX(x) FROM c"
        result = run_sql(endless, db_path=self.db, timeout_s=0.2)
        self.assertEqual(result["error"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()

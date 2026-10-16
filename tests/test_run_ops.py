# Tests for the ops measurement (eval/run_ops.py): the checks and the B2 baseline setup
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from eval.run_ops import RawSchemaAgent, check_case, raw_schema, result_rows, tool_check


def step(tool, args=None, result=None):
    return SimpleNamespace(tool=tool, args=args or {}, result=result or {})


TOP2 = {"id": "X", "expected_metric": "late_delivery_rate", "order_matters": True,
        "expected_rows": [["audio", 0.117816, 348], ["home_confort", 0.094388, 392]]}


class RunOpsChecksTest(unittest.TestCase):

    def test_result_is_the_last_data_step(self):
        steps = [step("list_metrics", result={"metrics": []}),
                 step("run_sql", result={"error": "SQL_ERROR"}),
                 step("run_metric", result={"rows": [["audio", 0.1178, 348]]})]
        self.assertEqual(result_rows(steps), [["audio", 0.1178, 348]])
        self.assertIsNone(result_rows([step("list_metrics", result={"metrics": []})]))

    def test_execution_match(self):
        good = [step("run_metric", {"metric_name": "late_delivery_rate"},
                     {"rows": [["audio", 0.1178, 348], ["home_confort", 0.0944, 392]]})]
        bad = [step("run_sql", {"query": "..."}, {"rows": [["audio", 0.1207, 348], ["christmas_supplies", 0.12, 125]]})]
        self.assertEqual(check_case(TOP2, good), "pass")
        self.assertEqual(check_case(TOP2, bad), "fail")
        self.assertEqual(check_case(TOP2, []), "fail")   # answered without data

    def test_tool_check_only_for_final(self):
        steps = [step("run_metric", {"metric_name": "late_delivery_rate"}, {"rows": []})]
        self.assertEqual(tool_check(TOP2, steps, "final"), "pass")
        self.assertEqual(tool_check(TOP2, [step("run_sql", {"query": "..."}, {"rows": []})], "final"), "fail")
        self.assertEqual(tool_check(TOP2, steps, "b2"), "")
        no_metric = {**TOP2, "expected_metric": None}
        self.assertEqual(tool_check(no_metric, [step("run_sql", {"query": "..."}, {"rows": []})], "final"), "pass")

    def test_sql_attack(self):
        attack = {"id": "O9", "expected_behavior": "SQL_BLOCKED"}
        blocked = [step("run_sql", {"query": "DROP TABLE orders"}, {"error": "NOT_SELECT"})]
        self.assertEqual(check_case(attack, blocked), "pass")
        self.assertEqual(check_case(attack, []), "pass")   # refused without a query
        self.assertEqual(check_case(attack, [step("run_sql", {}, {"rows": [], "sql": "DELETE FROM orders"})]), "fail")


class B2SetupTest(unittest.TestCase):

    def test_b2_sees_only_the_raw_schema_and_run_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE orders (order_id TEXT, order_status TEXT)")
            con.execute("CREATE TABLE return_requests (order_id TEXT)")
            con.close()
            schema = raw_schema(db)
        self.assertIn("CREATE TABLE orders", schema)
        self.assertNotIn("return_requests", schema)
        agent = RawSchemaAgent(schema, client=SimpleNamespace(models=None))
        self.assertEqual([d.name for d in agent.tool_declarations], ["run_sql"])
        self.assertIn("CREATE TABLE orders", agent.system_prompt)
        self.assertNotIn("run_metric", agent.system_prompt)
        self.assertNotIn("delivered", agent.system_prompt)   # no definitions from the semantic layer


if __name__ == "__main__":
    unittest.main()

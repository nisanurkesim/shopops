# Tests for the Ops Data Agent loop (guardrails G3, G4, G5)
# The LLM is replaced by FakeClient; the tools run on a small database.
import hashlib
import sqlite3
import tempfile
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.agents.ops_agent as ops_agent
import src.agents.ops_tools as ops_tools
from src.agents.support_tools import TOOL_DECLARATIONS as SUPPORT_TOOLS, execute_tool
from src.tools.metrics import run_metric
from src.tools.orders import Session
from src.tools.run_sql import run_sql


def call_response(name, args):
    """A fake Gemini response that asks for one tool call."""
    call = SimpleNamespace(name=name, args=args)
    return SimpleNamespace(function_calls=[call], text=None, usage_metadata=None,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


def text_response(text):
    return SimpleNamespace(function_calls=None, text=text, usage_metadata=None,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.models = self

    def generate_content(self, model, contents, config):
        return self.responses.pop(0)


class OpsAgentTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT, customer_state TEXT);
            CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_status TEXT,
                order_purchase_timestamp TEXT, order_approved_at TEXT, order_delivered_carrier_date TEXT,
                order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT);
        """)
        con.executemany("INSERT INTO customers VALUES (?, ?, ?)", [("c1", "u1", "SP"), ("c2", "u2", "RJ")])
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)", [
            ("A", "c1", "delivered", "2018-07-01 10:00:00", "2018-07-12 10:00:00", "2018-07-10 00:00:00"),
            ("B", "c1", "delivered", "2018-07-02 10:00:00", "2018-07-05 10:00:00", "2018-07-10 00:00:00"),
            ("C", "c2", "canceled", "2018-07-03 10:00:00", None, "2018-07-20 00:00:00"),
        ])
        con.commit()
        con.close()
        # The agent's tools run on the test database; count the real SQL executions
        self.sql_runs = 0

        def counted_run_sql(query):
            self.sql_runs += 1
            return run_sql(query, db_path=self.db)

        for name, fn in [("run_metric", partial(run_metric, db_path=self.db)), ("run_sql", counted_run_sql)]:
            patcher = mock.patch.object(ops_tools, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, responses):
        return ops_agent.OpsAgent(client=FakeClient(responses))

    def test_metric_question_uses_run_metric(self):
        agent = self.agent([
            call_response("list_metrics", {}),
            call_response("run_metric", {"metric_name": "late_delivery_rate", "filters": {"customer_state": "SP"}}),
            text_response("SP'de geç teslim oranı %50 (n = 2)."),
        ])
        reply = agent.ask("SP'de geç teslim oranı nedir?")
        self.assertIn("late_delivery_rate", [m["name"] for m in reply.steps[0].result["metrics"]])
        self.assertEqual(reply.steps[1].result["rows"], [[0.5, 2]])
        self.assertEqual(self.sql_runs, 0)

    def test_failed_query_can_be_corrected(self):
        agent = self.agent([
            call_response("run_sql", {"query": "SELECT status, COUNT(*) FROM orders GROUP BY 1"}),
            call_response("run_sql", {"query": "SELECT order_status, COUNT(*) FROM orders GROUP BY 1 ORDER BY 1"}),
            text_response("1 iptal, 2 teslim."),
        ])
        reply = agent.ask("Durumlara göre sipariş sayısı?")
        self.assertEqual(reply.steps[0].result["error"], "SQL_ERROR")
        self.assertEqual(reply.steps[1].result["rows"], [["canceled", 1], ["delivered", 2]])

    def test_at_most_two_corrections(self):
        bad = [f"SELECT wrong_column_{i} FROM orders" for i in range(4)]
        agent = self.agent([call_response("run_sql", {"query": q}) for q in bad]
                           + [text_response("Cevaplayamadım. Son denenen SQL: ...")])
        reply = agent.ask("Bir soru")
        self.assertEqual(self.sql_runs, 1 + ops_agent.MAX_SQL_CORRECTIONS)   # the 4th is not run
        self.assertIn("next", reply.steps[2].result)
        self.assertEqual(reply.steps[3].result["error"], "CORRECTION_LIMIT")

    def test_limit_counts_per_question(self):
        responses = []
        for i in range(3):
            responses.append(call_response("run_sql", {"query": f"SELECT bad_{i} FROM orders"}))
        responses.append(text_response("Cevaplayamadım."))
        responses.append(call_response("run_sql", {"query": "SELECT COUNT(*) FROM orders"}))
        responses.append(text_response("3 sipariş."))
        agent = self.agent(responses)
        agent.ask("Birinci soru")
        reply = agent.ask("İkinci soru")
        self.assertEqual(reply.steps[0].result["rows"], [[3]])

    def test_drop_through_the_agent_changes_nothing(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        agent = self.agent([
            call_response("run_sql", {"query": "SELECT 1; DROP TABLE orders; --"}),
            text_response("Bu sorgu çalıştırılamaz."),
        ])
        reply = agent.ask("'; DROP TABLE orders; --")
        self.assertEqual(reply.steps[0].result["error"], "MULTIPLE_STATEMENTS")
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_ops_agent_has_no_write_tools(self):
        names = {d.name for d in ops_tools.TOOL_DECLARATIONS}
        self.assertEqual(names, {"list_metrics", "run_metric", "run_sql"})

    def test_customer_session_cannot_reach_ops_tools(self):
        # G5: the Support Agent does not know these tools and refuses to run them
        support_names = {d.name for d in SUPPORT_TOOLS}
        self.assertFalse(support_names & {"list_metrics", "run_metric", "run_sql"})
        result = execute_tool(Session("u1"), "run_sql", {"query": "SELECT * FROM orders"})
        self.assertEqual(result["error"], "UNKNOWN_TOOL")


if __name__ == "__main__":
    unittest.main()

# Tests for human approval inside the Support Agent (guardrail G1)
# The LLM is replaced by FakeClient, which plays back prepared responses.
# The LLM can ask for a return request, but only confirm_return (the customer's
# answer in the interface) can write it.
import sqlite3
import tempfile
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.agents.support_agent as support_agent
from src.tools.orders import Session
from src.tools.return_requests import APPROVAL_REQUIRED

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
    order_id TEXT NOT NULL, reason TEXT NOT NULL, refund_amount REAL NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

# Alice's order, delivered 5 days ago, and Bob's order
ORDERS = [
    ("SMALL", "cid-1", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
    ("BOBS", "cid-2", "delivered", "2018-08-10 10:00:00", "2018-08-14 09:00:00", "2018-08-27 15:00:00", "2018-08-30 00:00:00"),
]


def call_response(name, args):
    """A fake Gemini response that asks for one tool call."""
    call = SimpleNamespace(name=name, args=args)
    return SimpleNamespace(function_calls=[call], text=None, usage_metadata=None,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


def text_response(text):
    """A fake Gemini response with a final answer."""
    return SimpleNamespace(function_calls=None, text=text, usage_metadata=None,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


class FakeClient:
    """Plays back prepared responses instead of calling Gemini."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.models = self

    def generate_content(self, model, contents, config):
        return self.responses.pop(0)


class AgentApprovalTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?, ?)", [("cid-1", "alice"), ("cid-2", "bob")])
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)",
                        [("SMALL", 100.0, 20.0, None), ("BOBS", 80.0, 10.0, None)])
        con.commit()
        con.close()
        # Point the agent's return functions at the test database
        for name in ("prepare_return_request", "create_return_request"):
            original = getattr(support_agent, name)
            patcher = mock.patch.object(support_agent, name, partial(original, db_path=self.db))
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        con = sqlite3.connect(self.db)
        rows = con.execute("SELECT order_id, reason, refund_amount, status FROM return_requests").fetchall()
        con.close()
        return rows

    def agent_after_llm_asks(self, order_id="SMALL"):
        """The LLM calls create_return_request, then answers the customer."""
        client = FakeClient([
            call_response("create_return_request", {"order_id": order_id, "reason": "damaged"}),
            text_response("Talebiniz onayınızı bekliyor."),
        ])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Kırık geldi, iade talebi açar mısınız?")
        return agent, reply

    def test_llm_call_alone_writes_nothing(self):
        agent, reply = self.agent_after_llm_asks()
        self.assertEqual(reply.steps[0].result["status"], APPROVAL_REQUIRED)
        self.assertIsNotNone(agent.pending)
        self.assertEqual(self.rows(), [])

    def test_token_is_not_in_the_conversation(self):
        agent, reply = self.agent_after_llm_asks()
        self.assertNotIn(agent.pending.token, str(reply.steps))
        self.assertNotIn(agent.pending.token, str(agent.history))

    def test_customer_says_no(self):
        agent, _ = self.agent_after_llm_asks()
        result = agent.confirm_return(False)
        self.assertEqual(result["status"], "CANCELLED_BY_CUSTOMER")
        self.assertIsNone(agent.pending)
        self.assertEqual(self.rows(), [])

    def test_customer_says_yes(self):
        agent, _ = self.agent_after_llm_asks()
        result = agent.confirm_return(True)
        self.assertIn("return_request_id", result)
        self.assertEqual(self.rows(), [("SMALL", "damaged", 120.0, "PENDING_REVIEW")])

    def test_approval_expires_with_the_next_message(self):
        agent, _ = self.agent_after_llm_asks()
        agent.client.responses.append(text_response("Başka bir konuda yardımcı olayım."))
        agent.ask("Aslında başka bir şey soracaktım.")
        self.assertEqual(agent.confirm_return(True)["error"], "NO_PENDING_REQUEST")
        self.assertEqual(self.rows(), [])

    def test_other_customers_order_is_not_prepared(self):
        agent, reply = self.agent_after_llm_asks(order_id="BOBS")
        self.assertEqual(reply.steps[0].result["error"], "NOT_FOUND")
        self.assertIsNone(agent.pending)


if __name__ == "__main__":
    unittest.main()
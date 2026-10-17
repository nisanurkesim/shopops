# Tests for the shopops-orders MCP server and the Support Agent as its client
# Each test starts a real server process (stdio) on a small test database, so identity
# and approval are checked where they run: in the server.
import sqlite3
import tempfile
import unittest
from pathlib import Path

import src.agents.support_agent as support_agent
from src.agents.mcp_orders import McpOrders
from src.tools.orders import Session
from tests.test_agent_approval import ORDERS, SCHEMA, FakeClient, call_response, text_response


def make_db(folder: str) -> Path:
    db = Path(folder) / "test.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO customers VALUES (?, ?)", [("cid-1", "alice"), ("cid-2", "bob")])
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS)
    con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)",
                    [("SMALL", 100.0, 20.0, None), ("BOBS", 80.0, 10.0, None)])
    con.commit()
    con.close()
    return db


class McpTestCase(unittest.TestCase):
    """A test database and a server for Alice. The server is stopped before the folder is removed."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = make_db(tmp.name)
        self.orders = McpOrders("alice", self.db)
        self.addCleanup(self.orders.close)   # runs first: Windows cannot remove a file in use

    def rows(self):
        con = sqlite3.connect(self.db)
        rows = con.execute("SELECT order_id, reason, status FROM return_requests").fetchall()
        con.close()
        return rows


class ServerTest(McpTestCase):

    def test_server_offers_the_order_tools(self):
        self.assertEqual(self.orders.tool_names, {
            "get_order_status", "list_customer_orders", "check_return_eligibility",
            "create_return_request", "confirm_return_request"})

    def test_foreign_order_looks_like_a_missing_one(self):
        self.assertEqual(self.orders.call("get_order_status", {"order_id": "SMALL"})["status"], "delivered")
        foreign = self.orders.call("get_order_status", {"order_id": "BOBS"})
        missing = self.orders.call("get_order_status", {"order_id": "NOPE"})
        self.assertEqual(foreign, missing)
        self.assertEqual(foreign["error"], "NOT_FOUND")

    def test_prepare_writes_nothing(self):
        result = self.orders.call("create_return_request", {"order_id": "SMALL", "reason": "damaged"})
        self.assertEqual(result["status"], "APPROVAL_REQUIRED")
        self.assertIn("approval_token", result)
        self.assertEqual(self.rows(), [])

    def test_only_the_right_token_writes(self):
        self.orders.call("create_return_request", {"order_id": "SMALL", "reason": "damaged"})
        refused = self.orders.call("confirm_return_request", {"approval_token": "guess", "approved": True})
        self.assertEqual(refused["error"], "APPROVAL_REQUIRED")
        self.assertEqual(self.rows(), [])

        token = self.orders.call("create_return_request",
                                 {"order_id": "SMALL", "reason": "damaged"})["approval_token"]
        written = self.orders.call("confirm_return_request", {"approval_token": token, "approved": True})
        self.assertIn("return_request_id", written)
        self.assertEqual(self.rows(), [("SMALL", "damaged", "PENDING_REVIEW")])

        # The same token cannot write a second request
        again = self.orders.call("confirm_return_request", {"approval_token": token, "approved": True})
        self.assertEqual(again["error"], "NO_PENDING_REQUEST")
        self.assertEqual(len(self.rows()), 1)

    def test_declined_request_is_not_written(self):
        token = self.orders.call("create_return_request",
                                 {"order_id": "SMALL", "reason": "damaged"})["approval_token"]
        result = self.orders.call("confirm_return_request", {"approval_token": token, "approved": False})
        self.assertEqual(result["status"], "CANCELLED_BY_CUSTOMER")
        self.assertEqual(self.rows(), [])


class AgentWithMcpTest(McpTestCase):

    def test_llm_never_sees_the_token_and_only_the_interface_writes(self):
        client = FakeClient([
            call_response("create_return_request", {"order_id": "SMALL", "reason": "damaged"}),
            text_response("Talebiniz hazır, lütfen ekrandan onaylayın."),
        ])
        agent = support_agent.SupportAgent(Session("alice"), client=client, orders=self.orders)
        reply = agent.ask("Siparişim kırık geldi, iade etmek istiyorum.")

        sent_to_llm = reply.steps[0].result
        self.assertEqual(sent_to_llm["status"], "APPROVAL_REQUIRED")
        self.assertNotIn("approval_token", sent_to_llm)
        self.assertIsNotNone(agent.pending)
        self.assertEqual(self.rows(), [])   # the LLM's call prepared, did not write

        result = agent.confirm_return(True)   # the customer's button in the interface
        self.assertIn("return_request_id", result)
        self.assertEqual(self.rows(), [("SMALL", "damaged", "PENDING_REVIEW")])

    def test_order_tools_go_through_the_server(self):
        client = FakeClient([
            call_response("get_order_status", {"order_id": "BOBS"}),
            text_response("Bu numarayla size ait bir sipariş bulunamadı."),
        ])
        agent = support_agent.SupportAgent(Session("alice"), client=client, orders=self.orders)
        reply = agent.ask("BOBS siparişim nerede?")
        self.assertEqual(reply.steps[0].result["error"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

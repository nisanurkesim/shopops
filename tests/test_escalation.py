# Tests for the handoff to a human representative (src/tools/escalation.py)
# The ticket goes to a local queue file; ids are masked and the customer is hashed (G6).
import json
import tempfile
import unittest
from pathlib import Path

from src.agents.support_tools import execute_tool
from src.agents.trace import hash_id
from src.tools.escalation import escalate_to_human
from src.tools.orders import Session

CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"
ORDER = "a1a6eadae352582010f449d8527b55f3"


class EscalationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "escalations.jsonl"
        self.session = Session(CUSTOMER)

    def tearDown(self):
        self.tmp.cleanup()

    def tickets(self):
        return [json.loads(line) for line in self.queue.read_text(encoding="utf-8").splitlines()]

    def test_ticket_is_queued(self):
        result = escalate_to_human(self.session, "Kargo bir aydir yolda.", "high", path=self.queue)
        self.assertEqual(result["ticket_id"], "ESC-0001")
        self.assertEqual(result["status"], "QUEUED")
        self.assertEqual(len(self.tickets()), 1)
        self.assertEqual(self.tickets()[0]["priority"], "high")

    def test_ticket_numbers_go_up(self):
        escalate_to_human(self.session, "Birinci sorun.", path=self.queue)
        second = escalate_to_human(self.session, "Ikinci sorun.", path=self.queue)
        self.assertEqual(second["ticket_id"], "ESC-0002")

    def test_no_raw_ids_in_the_queue(self):
        escalate_to_human(self.session, f"{ORDER} siparisi tahmini tarihi gecti.", path=self.queue)
        text = self.queue.read_text(encoding="utf-8")
        self.assertNotIn(ORDER, text)
        self.assertNotIn(CUSTOMER, text)
        self.assertEqual(self.tickets()[0]["session"], "#" + hash_id(CUSTOMER))

    def test_empty_summary_is_refused(self):
        result = escalate_to_human(self.session, "  ", path=self.queue)
        self.assertEqual(result["error"], "MISSING_SUMMARY")
        self.assertFalse(self.queue.exists())

    def test_unknown_priority_becomes_normal(self):
        escalate_to_human(self.session, "Bir sorun var.", "urgent", path=self.queue)
        self.assertEqual(self.tickets()[0]["priority"], "normal")

    def test_tool_is_reachable_from_the_agent(self):
        # execute_tool must route the call; a missing summary is a clear error, not a crash
        result = execute_tool(self.session, "escalate_to_human", {})
        self.assertEqual(result["error"], "MISSING_ARGUMENT")


if __name__ == "__main__":
    unittest.main()
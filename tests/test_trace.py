# Tests for the agent log (src/agents/trace.py, guardrail G6)
# The log must never contain a raw customer or order id.
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.agents.support_agent as support_agent
from src.agents.trace import cost_usd, hash_id, mask, outcome, result_summary
from src.tools.orders import Session

CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"
ORDER = "a1a6eadae352582010f449d8527b55f3"


def response(text=None, call=None, usage=None):
    """A fake Gemini response: a tool call or a final answer."""
    calls = [SimpleNamespace(name=call[0], args=call[1])] if call else None
    return SimpleNamespace(function_calls=calls, text=text, usage_metadata=usage,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


def usage(prompt, output, thinking):
    return SimpleNamespace(prompt_token_count=prompt, candidates_token_count=output, thoughts_token_count=thinking)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.models = self

    def generate_content(self, model, contents, config):
        return self.responses.pop(0)


class MaskTest(unittest.TestCase):

    def test_hash_is_short_and_stable(self):
        self.assertEqual(len(hash_id(ORDER)), 10)
        self.assertEqual(hash_id(ORDER), hash_id(ORDER))
        self.assertNotEqual(hash_id(ORDER), hash_id(CUSTOMER))

    def test_ids_in_text_are_replaced(self):
        text = f"{ORDER} siparişim nerede?"
        self.assertEqual(mask(text), f"#{hash_id(ORDER)} siparişim nerede?")

    def test_short_order_id_is_replaced(self):
        # The agent writes only the first 8 characters of an order id
        self.assertEqual(mask(f"{ORDER[:8]} teslim edildi"), f"#{hash_id(ORDER[:8])} teslim edildi")

    def test_dates_amounts_and_words_are_kept(self):
        text = "10.08.2018 tarihinde teslim edildi, 96.40 BRL, 2018-08-13, cafe"
        self.assertEqual(mask(text), text)

    def test_hash_is_not_masked_again(self):
        masked = mask(ORDER)
        self.assertEqual(mask(masked), masked)

    def test_nested_values_are_masked(self):
        masked = mask({"args": {"order_id": ORDER}, "list": [CUSTOMER], "count": 3})
        self.assertEqual(masked["args"]["order_id"], "#" + hash_id(ORDER))
        self.assertEqual(masked["list"], ["#" + hash_id(CUSTOMER)])
        self.assertEqual(masked["count"], 3)

    def test_outcome(self):
        self.assertEqual(outcome({"error": "NOT_FOUND"}), "NOT_FOUND")
        self.assertEqual(outcome({"code": "ELIGIBLE", "status": "x"}), "ELIGIBLE")
        self.assertEqual(outcome({"orders": []}), "ok")


class CostAndSummaryTest(unittest.TestCase):

    def test_cost_counts_thinking_as_output(self):
        # 1M input = 0.30 USD, 1M output = 2.50 USD (config.py)
        self.assertAlmostEqual(cost_usd(1_000_000, 0), 0.30)
        self.assertAlmostEqual(cost_usd(0, 500_000, 500_000), 2.50)

    def test_sql_rows_are_not_in_the_summary(self):
        result = {"columns": ["customer_city", "n"], "rows": [["sao paulo", 3]], "row_count": 1, "sql": "SELECT 1"}
        summary = result_summary("run_sql", result)
        self.assertEqual(summary["row_count"], 1)
        self.assertNotIn("sao paulo", json.dumps(summary))

    def test_policy_summary_and_flag(self):
        result = {"results": [{"title": "İade Politikası", "section": "Süre", "text": "uzun metin"}],
                  "suspicious_content": [{"where": "results[0].text", "pattern": "role_change"}]}
        summary = result_summary("search_policies", result)
        self.assertEqual(summary["hits"], ["İade Politikası / Süre"])
        self.assertEqual(summary["suspicious"], ["role_change"])

    def test_metric_list_shows_names(self):
        result = {"metrics": [{"name": "gmv", "description": "uzun"}, {"name": "order_count"}]}
        self.assertEqual(result_summary("list_metrics", result)["metrics"], ["gmv", "order_count"])

    def test_long_results_are_cut(self):
        summary = result_summary("list_customer_orders", {"orders": ["x" * 50] * 20})
        self.assertTrue(summary["text"].endswith("..."))
        self.assertLessEqual(len(summary["text"]), 303)


class AgentLogTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "agent_log.jsonl"
        # The tool itself is not tested here, so it returns a fixed result
        patcher = mock.patch.object(support_agent, "execute_tool",
                                    return_value={"order_id": ORDER, "status": "delivered"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_turn(self, log_path):
        client = FakeClient([response(call=("get_order_status", {"order_id": ORDER})),
                             response(text=f"{ORDER[:8]} siparişiniz teslim edildi.")])
        agent = support_agent.SupportAgent(Session(CUSTOMER), client=client, log_path=log_path)
        agent.ask(f"{ORDER} siparişim nerede? Müşteri numaram {CUSTOMER}.")

    def test_turn_is_logged_without_raw_ids(self):
        self.run_turn(self.log)
        text = self.log.read_text(encoding="utf-8")
        self.assertNotIn(ORDER[:8], text)   # not even the short form in the reply
        self.assertNotIn(CUSTOMER, text)
        event = json.loads(text)
        self.assertEqual(event["session"], "#" + hash_id(CUSTOMER))
        self.assertEqual(event["steps"][0]["args"]["order_id"], "#" + hash_id(ORDER))
        self.assertEqual(event["steps"][0]["outcome"], "delivered")
        self.assertIn("latency_s", event)

    def test_trace_fields_are_logged(self):
        client = FakeClient([response(call=("get_order_status", {"order_id": ORDER}), usage=usage(1000, 20, 300)),
                             response(text="Teslim edildi.", usage=usage(1200, 40, 0))])
        agent = support_agent.SupportAgent(Session(CUSTOMER), client=client, log_path=self.log)
        reply = agent.ask("Siparişim nerede?")
        self.assertEqual(reply.thinking_tokens, 300)
        self.assertAlmostEqual(reply.cost_usd, cost_usd(2200, 60, 300))
        event = json.loads(self.log.read_text(encoding="utf-8"))
        self.assertEqual(event["thinking_tokens"], 300)
        self.assertEqual(event["model_calls"][0]["thinking_tokens"], 300)
        self.assertIn("cost_usd", event["model_calls"][0])
        step = event["steps"][0]
        self.assertEqual(step["call"], 0)        # asked for by the first model call
        self.assertIn("latency_s", step)
        self.assertEqual(step["result"]["outcome"], "delivered")
        self.assertNotIn(ORDER, self.log.read_text(encoding="utf-8"))

    def test_no_log_path_writes_nothing(self):
        self.run_turn(None)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
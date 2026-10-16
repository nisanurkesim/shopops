# Tests for the loop limits of the Support Agent (guardrail G10)
# MAX_STEPS: at most 8 model calls per customer message.
# MAX_SAME_CALL: the same tool with the same arguments runs at most twice.
# The LLM is replaced by FakeClient and the tools by a mock, so no quota is used.
import unittest
from types import SimpleNamespace
from unittest import mock

import src.agents.support_agent as support_agent
from src.tools.orders import Session


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
    """Plays back prepared responses and counts the model calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls += 1
        return self.responses.pop(0)


class LoopLimitTest(unittest.TestCase):

    def setUp(self):
        # Every tool call returns the same fixed result; the loop is what is tested
        patcher = mock.patch.object(support_agent, "execute_tool", return_value={"results": []})
        self.execute_tool = patcher.start()
        self.addCleanup(patcher.stop)

    def test_stops_after_max_steps(self):
        # The model never answers: it asks for a new search every time
        responses = [call_response("search_policies", {"query": f"soru {i}"}) for i in range(20)]
        client = FakeClient(responses)
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Bir sorum var.")

        self.assertEqual(client.calls, support_agent.MAX_STEPS)
        self.assertEqual(reply.stop_reason, "max_steps")
        self.assertEqual(reply.text, support_agent.MAX_STEPS_MESSAGE)

    def test_turn_is_closed_after_max_steps(self):
        # The history ends with the safe message, so the next question starts cleanly
        responses = [call_response("search_policies", {"query": f"soru {i}"}) for i in range(20)]
        agent = support_agent.SupportAgent(Session("alice"), client=FakeClient(responses))
        agent.ask("Bir sorum var.")

        self.assertEqual(agent.history[-1].role, "model")

    def test_same_call_runs_at_most_twice(self):
        same = call_response("get_order_status", {"order_id": "X"})
        client = FakeClient([same, same, same, text_response("Bilgi bulunamadı.")])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("X siparişim nerede?")

        self.assertEqual(self.execute_tool.call_count, support_agent.MAX_SAME_CALL)
        self.assertEqual(reply.steps[2].result["error"], "REPEATED_CALL")
        self.assertEqual(reply.stop_reason, "answer")

    def test_different_arguments_are_not_blocked(self):
        client = FakeClient([
            call_response("get_order_status", {"order_id": "A"}),
            call_response("get_order_status", {"order_id": "B"}),
            call_response("get_order_status", {"order_id": "C"}),
            text_response("Üç siparişe baktım."),
        ])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        agent.ask("A, B ve C siparişlerim nerede?")

        self.assertEqual(self.execute_tool.call_count, 3)


if __name__ == "__main__":
    unittest.main()
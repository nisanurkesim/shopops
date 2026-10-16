# Tests for timing and retrying model calls (error analysis 8)
# Every model call is recorded with its time and error, so a slow turn can be explained.
import unittest
from types import SimpleNamespace
from unittest import mock

from google.genai import errors

import src.agents.support_agent as support_agent
from src.tools.orders import Session


def text_response(text):
    """A fake Gemini response with a final answer and token counts."""
    usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=10)
    return SimpleNamespace(function_calls=None, text=text, usage_metadata=usage,
                           candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


class FakeClient:
    """Raises the prepared errors first, then plays back the responses."""

    def __init__(self, items):
        self.items = list(items)
        self.models = self

    def generate_content(self, model, contents, config):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ModelCallTest(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(support_agent.time, "sleep")   # do not really wait
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_call_is_recorded(self):
        agent = support_agent.SupportAgent(Session("alice"), client=FakeClient([text_response("Merhaba")]))
        reply = agent.ask("Selam")
        self.assertEqual(len(reply.model_calls), 1)
        self.assertEqual(reply.model_calls[0]["input_tokens"], 100)
        self.assertIsNone(reply.model_calls[0]["error"])

    def test_timeout_is_retried_and_recorded(self):
        client = FakeClient([TimeoutError("read timed out"), text_response("Merhaba")])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Selam")
        self.assertEqual(reply.stop_reason, "answer")
        self.assertEqual(len(reply.model_calls), 2)
        self.assertIn("TimeoutError", reply.model_calls[0]["error"])

    def test_gives_up_after_the_retries(self):
        client = FakeClient([TimeoutError("read timed out")] * (support_agent.MAX_API_RETRIES + 1))
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Selam")
        self.assertEqual(reply.stop_reason, "api_error")
        self.assertEqual(len(reply.model_calls), support_agent.MAX_API_RETRIES + 1)

    def test_cancelled_call_is_retried(self):
        # 499 came back once in the eval run and ended the turn (error analysis 8)
        client = FakeClient([errors.ClientError(499, "The operation was cancelled."), text_response("Merhaba")])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Selam")
        self.assertEqual(reply.stop_reason, "answer")
        self.assertIn("499", reply.model_calls[0]["error"])

    def test_quota_error_is_not_retried(self):
        client = FakeClient([errors.ClientError(429, "Quota exceeded"), text_response("Merhaba")])
        agent = support_agent.SupportAgent(Session("alice"), client=client)
        reply = agent.ask("Selam")
        self.assertEqual(reply.stop_reason, "api_error")
        self.assertEqual(len(reply.model_calls), 1)


if __name__ == "__main__":
    unittest.main()
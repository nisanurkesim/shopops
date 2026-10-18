# Tests for the trace report (eval/trace_report.py) and the trace page (scripts/trace_view.py)
# They use made-up log lines, so no Gemini call is made.
import unittest

from eval.trace_report import log_section, percentile, traced_turns
from scripts.trace_view import turn_card


def turn(session="ops", latency=10.0, thinking=100, steps=None, calls=None):
    return {"event": "turn", "time": "2026-10-18T15:00:00", "session": session, "message": "soru", "reply": "cevap",
            "input_tokens": 3000, "output_tokens": 50, "thinking_tokens": thinking, "cost_usd": 0.001,
            "latency_s": latency, "stop_reason": "answer",
            "model_calls": calls if calls is not None else [{"latency_s": 4.0, "input_tokens": 1500, "output_tokens": 10,
                                                              "thinking_tokens": thinking, "error": None},
                                                             {"latency_s": 5.0, "input_tokens": 1500, "output_tokens": 40,
                                                              "thinking_tokens": 0, "error": None}],
            "steps": steps if steps is not None else [{"tool": "run_metric", "args": {"metric_name": "gmv"}, "call": 0,
                                                       "latency_s": 0.4, "outcome": "ok",
                                                       "result": {"outcome": "ok", "row_count": 1}}]}


class PercentileTest(unittest.TestCase):

    def test_nearest_rank(self):
        values = list(range(1, 21))   # 1..20
        self.assertEqual(percentile(values, 50), 10)
        self.assertEqual(percentile(values, 95), 19)
        self.assertEqual(percentile([7], 95), 7)
        self.assertEqual(percentile([], 50), 0.0)


class LogSectionTest(unittest.TestCase):

    def test_old_lines_without_trace_fields_are_skipped(self):
        old = {"event": "turn", "session": "ops", "latency_s": 3.0, "steps": [], "model_calls": []}
        self.assertEqual(traced_turns([old, turn()]), [turn()])

    def test_section_has_sessions_tools_and_time_split(self):
        text = "\n".join(log_section([turn(), turn(session="#abc1234567")]))
        self.assertIn("| customer | 1 |", text)
        self.assertIn("| ops | 1 |", text)
        self.assertIn("| `run_metric` | 2 |", text)
        self.assertIn("90% in model calls", text)   # 9 of 10 seconds

    def test_empty_log(self):
        self.assertIn("No traced turns", log_section([])[0])


class TurnCardTest(unittest.TestCase):

    def test_steps_follow_their_model_call(self):
        card = turn_card(turn())
        self.assertLess(card.index("model call 1"), card.index("run_metric"))
        self.assertLess(card.index("run_metric"), card.index("model call 2"))

    def test_text_is_escaped_and_flag_shown(self):
        t = turn(steps=[{"tool": "run_sql", "args": {"query": "<script>"}, "call": 0, "latency_s": 0.1,
                         "result": {"outcome": "ok", "suspicious": ["role_change"]}}])
        t["reply"] = "<b>cevap</b>"
        card = turn_card(t)
        self.assertNotIn("<script>", card)
        self.assertNotIn("<b>cevap</b>", card)
        self.assertIn("suspicious content flagged", card)

    def test_failed_call_is_marked(self):
        t = turn(calls=[{"latency_s": 60.0, "error": "503: busy"}], steps=[])
        self.assertIn("model err", turn_card(t))


if __name__ == "__main__":
    unittest.main()

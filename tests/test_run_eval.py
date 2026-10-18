# Tests for the results table of eval/run_eval.py
# Only the counting is tested, on small made-up rows; no step is run and no model is called.
import tempfile
import unittest
from pathlib import Path

from eval import run_eval as re_


class CountTest(unittest.TestCase):

    def test_frac(self):
        self.assertEqual(re_.frac(7, 8), "7/8 (88%)")
        self.assertEqual(re_.frac(0, 0), "-")

    def test_hallucination_says_what_is_not_labelled(self):
        rows = [{"id": "S1", "hallucinated": "no"}, {"id": "S2", "hallucinated": "yes-order"},
                {"id": "S3", "hallucinated": ""}]
        self.assertEqual(re_.hallucination(rows), "1/2 (50%), 1 not labelled")

    def test_judge_scores_count_claims(self):
        rows = [{"system": "B0", "error": "", "n_claims": "3", "n_supported": "3", "helpfulness": "5"},
                {"system": "B0", "error": "", "n_claims": "1", "n_supported": "0", "helpfulness": "2"},
                {"system": "B0", "error": "bad judge answer", "n_claims": "", "n_supported": "", "helpfulness": ""}]
        self.assertEqual(re_.judge_scores(rows, "B0"), ("0.75 (3/4)", "3.50"))
        self.assertEqual(re_.judge_scores(rows, "B1"), ("-", "-"))

    def test_access_needs_every_tool_hidden(self):
        rows = [{"order_id": "a", "not_found": "True", "same_as_missing_order": "True"},
                {"order_id": "a", "not_found": "True", "same_as_missing_order": "True"},
                {"order_id": "b", "not_found": "True", "same_as_missing_order": "False"}]
        self.assertEqual(re_.access_result(rows), "1/2 (50%)")

    def test_injection_counts_model_runs_only(self):
        rows = [{"kind": "code", "layer": "code", "result": "pass", "rows_written": "", "error": ""},
                {"kind": "model", "layer": "router+agent", "result": "pass", "rows_written": "0", "error": ""},
                {"kind": "model", "layer": "agent only", "result": "pass", "rows_written": "0", "error": ""},
                {"kind": "model", "layer": "router+agent", "result": "", "rows_written": "", "error": "429"}]
        self.assertEqual(re_.injection_result(rows), ("0 rows in 2 runs", "1/1 (100%)"))

    def test_support_metrics(self):
        golden = {"S1": {"expected_tool": "get_order_status"},
                  "S2": {"expected_tool": "check_return_eligibility", "expected_code": "ELIGIBLE"},
                  "S12": {"expected_behavior": "CLARIFY"}}
        rows = [{"id": "S1", "group": "support", "answer": "x", "error": "", "check": "pass",
                 "hallucinated": "no", "tools": "get_order_status -> delivered"},
                {"id": "S2", "group": "support", "answer": "x", "error": "", "check": "fail",
                 "hallucinated": "no", "tools": "get_order_status -> delivered"},
                {"id": "S12", "group": "support", "answer": "x", "error": "", "check": "pass",
                 "hallucinated": "no", "tools": ""}]
        self.assertEqual(re_.support_metrics(rows, golden),
                         {"success": "2/3 (67%)", "tools": "1/2 (50%)", "decisions": "0/1 (0%)"})

    def test_ops_metrics_leave_out_the_attack(self):
        rows = [{"id": "O1", "match": "pass", "tool_check": "pass", "error": ""},
                {"id": "O2", "match": "fail", "tool_check": "pass", "error": ""},
                {"id": "O9", "match": "pass", "tool_check": "", "error": ""}]
        self.assertEqual(re_.ops_metrics(rows), {"sql": "1/2 (50%)", "tools": "2/2 (100%)"})


class TableTest(unittest.TestCase):

    def test_table_has_the_four_rows_even_without_results(self):
        with tempfile.TemporaryDirectory() as folder:
            lines = re_.build_table(Path(folder))
        table = [line for line in lines if line.startswith("| ")]
        self.assertEqual(len(table), 6)   # header, target and B0, B1, B2, Final
        for name in ("B0:", "B1:", "B2:", "Final:"):
            self.assertTrue(any(line.startswith(f"| {name}") for line in table), name)


if __name__ == "__main__":
    unittest.main()

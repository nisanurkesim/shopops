# Tests for the LLM-as-judge script (eval/run_judge.py)
# Only the parsing and scoring are tested. No Gemini call is made, so no quota is used.
import json
import unittest

from eval import run_judge as rj

VERDICT = {"claims": [{"claim": "Hasarlı ürün için süre 30 gün.", "verdict": "supported",
                       "source": "Hasarlı veya Yanlış Ürün - Başvuru süresi"},
                      {"claim": "İade 7 gün içinde hesaba geçer.", "verdict": "unsupported", "source": ""}],
           "helpfulness": 4, "helpfulness_reason": "Doğru, süreyi söylüyor."}


class ParseTest(unittest.TestCase):

    def test_plain_and_wrapped_json(self):
        text = json.dumps(VERDICT, ensure_ascii=False)
        self.assertEqual(rj.parse_verdict(text)["helpfulness"], 4)
        self.assertEqual(len(rj.parse_verdict(f"```json\n{text}\n```")["claims"]), 2)

    def test_no_claims_is_allowed(self):
        verdict = rj.parse_verdict('{"claims": [], "helpfulness": 1, "helpfulness_reason": "Cevap yok."}')
        self.assertEqual(rj.score_row(verdict)["faithfulness"], "")

    def test_wrong_forms_are_refused(self):
        for text in ("Cevap iyi.", '{"claims": "yok", "helpfulness": 3}',
                     '{"claims": [{"claim": "x", "verdict": "maybe"}], "helpfulness": 3}',
                     '{"claims": [], "helpfulness": 7}', '{"claims": [], "helpfulness": "4"}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    rj.parse_verdict(text)


class ScoreTest(unittest.TestCase):

    def test_score_row(self):
        row = rj.score_row(rj.parse_verdict(json.dumps(VERDICT)))
        self.assertEqual((row["n_claims"], row["n_supported"], row["faithfulness"]), (2, 1, 0.5))

    def test_summary_counts_claims_not_answers(self):
        rows = [{"system": "B0", "error": "", "n_claims": "4", "n_supported": "3", "helpfulness": "2"},
                {"system": "B0", "error": "", "n_claims": "0", "n_supported": "0", "helpfulness": "4"},
                {"system": "B0", "error": "bad judge answer", "n_claims": "", "n_supported": "", "helpfulness": ""}]
        s = rj.summary(rows)["B0"]
        self.assertEqual((s["answers"], s["claims"], s["supported"]), (2, 4, 3))
        self.assertAlmostEqual(s["faithfulness"], 0.75)
        self.assertAlmostEqual(s["helpfulness"], 3.0)

    def test_answer_fingerprint_changes_with_the_answer(self):
        self.assertEqual(rj.answer_sha("aynı"), rj.answer_sha("aynı"))
        self.assertNotEqual(rj.answer_sha("bir"), rj.answer_sha("iki"))


class PromptTest(unittest.TestCase):

    def test_prompt_has_the_codes_and_the_policies(self):
        instruction = rj.system_instruction()
        for code in ("NOT_ELIGIBLE_WINDOW", "CLARIFY", "NOT_FOUND", '"helpfulness"'):
            self.assertIn(code, instruction)
        self.assertIn("# Hasarlı veya Yanlış Ürün", instruction)

    def test_prompt_explains_order_facts_and_the_approval(self):
        # Added after the first run: order facts are not policy claims, a prepared request is right
        instruction = rj.system_instruction()
        self.assertIn("politika iddiası değildir", instruction)
        self.assertIn("ekrandan onaylayın", instruction)

    def test_message_has_question_expected_and_answer(self):
        text = rj.user_message("Soru?", "cite return_policy.md", "Cevap.")
        self.assertIn("Soru?", text)
        self.assertIn("cite return_policy.md", text)
        self.assertTrue(text.endswith("Cevap."))


if __name__ == "__main__":
    unittest.main()

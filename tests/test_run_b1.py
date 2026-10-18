# Tests for baseline B1, naive RAG (eval/run_b1.py)
# No Gemini call and no search is made, so no quota is used.
import unittest

from eval import run_b1

HITS = [{"title": "Hasarlı veya Yanlış Ürün", "section": "Ne yapmalı", "text": "Fotoğrafla bildirin."},
        {"title": "İade Politikası", "section": "Süre", "text": "14 gün içinde."}]


class B1Test(unittest.TestCase):

    def test_prompt_has_the_sections_and_the_question(self):
        prompt = run_b1.build_prompt("Hasarlı ürün gelirse ne yapmam gerekiyor?", HITS)
        self.assertIn("[Hasarlı veya Yanlış Ürün - Ne yapmalı]", prompt)
        self.assertIn("14 gün içinde.", prompt)
        self.assertTrue(prompt.endswith("Hasarlı ürün gelirse ne yapmam gerekiyor?"))

    def test_policy_check_needs_the_source_retrieved_and_named(self):
        case = {"group": "policy", "expected_doc": "damaged_or_wrong_item.md"}
        title = run_b1.doc_title("damaged_or_wrong_item.md")
        hits = [{**HITS[0], "title": title}]
        self.assertEqual(run_b1.check_case(case, hits, f"Kaynak: {title}")[0], "pass")
        self.assertEqual(run_b1.check_case(case, hits, "Fotoğrafla bildirin.")[0], "fail")
        self.assertEqual(run_b1.check_case(case, HITS[1:], f"Kaynak: {title}")[0], "fail")

    def test_other_groups_have_no_automatic_check(self):
        self.assertEqual(run_b1.check_case({"group": "support"}, HITS, "..."), ("", ""))
        self.assertEqual(run_b1.check_case({"group": "policy", "expected_behavior": "NOT_IN_POLICY"}, HITS, "..."),
                         ("", ""))


if __name__ == "__main__":
    unittest.main()

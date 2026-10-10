# Tests for the policy RAG (src/knowledge/policies.py)
# Splitting tests always run. Search tests need the index:
#   python scripts/build_index.py
import unittest

from src.knowledge.policies import INDEX_DIR, load_chunks, search_policies

EXPECTED_DOCUMENTS = {
    "return_policy.md", "damaged_or_wrong_item.md", "shipping_and_delivery.md",
    "late_delivery.md", "cancellation_policy.md", "payments_and_refunds.md",
    "account_and_privacy.md",
}


class TestSplitting(unittest.TestCase):

    def test_all_seven_documents_are_loaded(self):
        documents = {c.document for c in load_chunks()}
        self.assertEqual(documents, EXPECTED_DOCUMENTS)

    def test_readme_is_not_indexed(self):
        self.assertNotIn("README.md", {c.document for c in load_chunks()})

    def test_every_chunk_has_title_section_and_text(self):
        for c in load_chunks():
            with self.subTest(chunk=c.chunk_id):
                self.assertTrue(c.title)
                self.assertTrue(c.section)
                self.assertTrue(c.body)

    def test_chunk_ids_are_unique(self):
        ids = [c.chunk_id for c in load_chunks()]
        self.assertEqual(len(ids), len(set(ids)))


@unittest.skipUnless(INDEX_DIR.exists(), "index not built: run python scripts/build_index.py")
class TestSearch(unittest.TestCase):

    def assert_in_top_3(self, query, expected_document):
        hits = search_policies(query, k=3)
        documents = [h["document"] for h in hits]
        self.assertIn(expected_document, documents, f"query: {query!r}, got: {documents}")

    def test_damaged_item(self):
        # Required by the brief (section 8, step 4)
        self.assert_in_top_3("hasarlı ürün", "damaged_or_wrong_item.md")

    def test_cancel_order(self):
        self.assert_in_top_3("siparişimi iptal etmek istiyorum", "cancellation_policy.md")

    def test_late_delivery_freight(self):
        self.assert_in_top_3("ürün çok geç geldi, kargo ücretimi geri alabilir miyim", "late_delivery.md")

    def test_someone_elses_order(self):
        self.assert_in_top_3("başkasının siparişini görebilir miyim", "account_and_privacy.md")

    def test_results_have_source_fields(self):
        hit = search_policies("iade süresi", k=1)[0]
        for key in ["document", "title", "section", "text", "score"]:
            self.assertIn(key, hit)


if __name__ == "__main__":
    unittest.main()
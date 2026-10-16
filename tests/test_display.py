# Tests for what the user sees (src/display.py): shortened ids, the approval summary
# built from the code's data, and the ops result table
import unittest
from types import SimpleNamespace

from src.display import approval_lines, confirmation_text, hide_ids, last_table, step_text

ORDER = "a1a6eadae352582010f449d8527b55f3"


class DisplayTest(unittest.TestCase):

    def test_full_ids_are_shortened(self):
        self.assertEqual(hide_ids(f"Sipariş {ORDER} teslim edildi"), "Sipariş a1a6eada... teslim edildi")
        self.assertEqual(hide_ids("a1a6eada"), "a1a6eada")   # an order_ref stays as it is

    def test_step_text_hides_ids_and_shows_sql(self):
        status = SimpleNamespace(tool="get_order_status", args={"order_id": ORDER}, result={"status": "delivered"})
        self.assertNotIn(ORDER, step_text(status))
        sql = SimpleNamespace(tool="run_sql", args={"query": "SELECT 1"}, result={"rows": [[1]]})
        self.assertTrue(step_text(sql).startswith("run_sql(SELECT 1)"))

    def test_approval_summary_uses_turkish_labels(self):
        summary = {"order_id": ORDER, "reason": "damaged", "refund_amount": 67.344,
                   "currency": "BRL", "approval_level": "PENDING_SENIOR"}
        lines = approval_lines(summary)
        self.assertEqual(lines, ["Sipariş: a1a6eada", "Sebep: Hasarlı ürün", "İade tutarı: 67.34 BRL",
                                 "Sonraki adım: kıdemli temsilci onayı"])

    def test_confirmation_text(self):
        self.assertEqual(confirmation_text({"return_request_id": 5}), "Talep oluşturuldu. Talep numarası: 5")
        self.assertEqual(confirmation_text({"status": "CANCELLED_BY_CUSTOMER"}), "Talep oluşturulmadı.")
        self.assertIn("NO_PENDING_REQUEST", confirmation_text({"error": "NO_PENDING_REQUEST"}))

    def test_last_table_is_the_last_data_step(self):
        steps = [SimpleNamespace(tool="list_metrics", args={}, result={"metrics": []}),
                 SimpleNamespace(tool="run_metric", args={}, result={
                     "columns": ["late_delivery_rate", "n"], "rows": [[0.0672, 96417]],
                     "sql": "SELECT ...", "caveat": "Gözlemsel oran"})]
        table = last_table(steps)
        self.assertEqual(table["rows"], [[0.0672, 96417]])
        self.assertEqual(table["caveat"], "Gözlemsel oran")
        self.assertIsNone(last_table(steps[:1]))


if __name__ == "__main__":
    unittest.main()

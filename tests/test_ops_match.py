# Tests for execution match (eval/ops_match.py)
import unittest

from eval.ops_match import rows_match, values_match


class ValuesMatchTest(unittest.TestCase):

    def test_rounded_number_matches(self):
        self.assertTrue(values_match(0.0672, 0.067218))
        self.assertTrue(values_match(12.54, 12.540185))
        self.assertTrue(values_match(12.5, 12.540185))

    def test_wrong_definition_does_not_match(self):
        self.assertFalse(values_match(0.0677, 0.067218))   # deliveries after today included
        self.assertFalse(values_match(0.0806, 0.067218))   # timestamps instead of days
        self.assertFalse(values_match(12.48, 12.540185))   # days instead of timestamps

    def test_counts_and_text(self):
        self.assertTrue(values_match(96417, 96417.0))
        self.assertFalse(values_match(96470, 96417))
        self.assertTrue(values_match("sp", "SP"))
        self.assertFalse(values_match("baby", "office_furniture"))


class RowsMatchTest(unittest.TestCase):

    def test_extra_columns_and_rows_are_allowed(self):
        golden = [["2018-01", 945456.29], ["2018-02", 837895.43]]
        shown = [["2017-12", 1.0, 5], ["2018-01", 945456.29, 7000], ["2018-02", 837895.43, 6500]]
        self.assertTrue(rows_match(shown, golden, order_matters=False))

    def test_order_counts_for_top_n(self):
        golden = [["audio", 0.117816, 348], ["home_confort", 0.094388, 392]]
        self.assertTrue(rows_match([["audio", 0.1178, 348], ["home_confort", 0.0944, 392]], golden, True))
        self.assertFalse(rows_match([["home_confort", 0.0944, 392], ["audio", 0.1178, 348]], golden, True))
        self.assertTrue(rows_match([["home_confort", 0.0944, 392], ["audio", 0.1178, 348]], golden, False))

    def test_missing_row_fails(self):
        golden = [["PR", 0.076822, 7589], ["MG", 0.056589, 7846]]
        self.assertFalse(rows_match([["PR", 0.0768, 7589]], golden, True))
        self.assertFalse(rows_match([["PR", 0.0768, 7589], ["SP", 0.0558, 69497]], golden, False))


if __name__ == "__main__":
    unittest.main()

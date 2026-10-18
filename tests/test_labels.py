# Tests for eval/labels.py: a manual label is applied only to the answer it was made for
import csv
import tempfile
import unittest
from pathlib import Path

from eval.labels import answer_sha, apply_labels


class ApplyLabelsTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "rows.csv"
        with self.path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "answer", "hallucinated"])
            writer.writeheader()
            writer.writerows([{"id": "S1", "answer": "Teslim edildi.", "hallucinated": "old"},
                              {"id": "S2", "answer": "Yeni cevap.", "hallucinated": "old"},
                              {"id": "S3", "answer": "Etiketsiz.", "hallucinated": ""}])

    def test_label_goes_only_to_the_labelled_answer(self):
        labels = {"S1": "no", "S2": "yes-order"}
        answers = {"S1": answer_sha("Teslim edildi."), "S2": answer_sha("Eski cevap.")}
        rows, changed = apply_labels(self.path, labels, answers)
        self.assertEqual(changed, ["S2"])
        self.assertEqual([r["hallucinated"] for r in rows], ["no", "", ""])
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            saved = list(csv.DictReader(f))
        self.assertEqual(saved[1]["hallucinated"], "")   # the old label was not kept either

    def test_the_committed_labels_match_the_committed_answers(self):
        from eval import label_agent, label_b1, label_baseline
        for module in (label_baseline, label_b1, label_agent):
            with self.subTest(module=module.__name__):
                self.assertEqual(set(module.LABELS), set(module.ANSWERS))
                with module.PATH.open(encoding="utf-8-sig", newline="") as f:
                    rows = {r["id"]: r["answer"] for r in csv.DictReader(f)}
                stale = [i for i, sha in module.ANSWERS.items() if answer_sha(rows[i]) != sha]
                self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()

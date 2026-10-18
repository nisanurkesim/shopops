# Apply manual labels to a result file, but only to the answers they were made for
# A label is decided by reading one answer. If that question is run again and gets a new
# answer, the old label must not be copied onto it. So every label script also keeps a
# fingerprint of each labelled answer; a row whose answer has changed gets no label and is
# reported, and compare.py and run_eval.py then show that it still needs one.
import csv
import hashlib
from pathlib import Path


def answer_sha(text: str) -> str:
    """A short fingerprint of a text (the first 12 characters of its SHA-256)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def apply_labels(path: Path, labels: dict[str, str], answers: dict[str, str],
                 field: str = "hallucinated") -> tuple[list[dict], list[str]]:
    """Write the labels into the result file. Returns the rows and the ids whose answer has
    changed since it was labelled (their label is left empty)."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    changed = []
    for row in rows:
        if row["id"] not in labels:
            continue
        if answers.get(row["id"]) == answer_sha(row["answer"]):
            row[field] = labels[row["id"]]
        else:
            row[field] = ""
            changed.append(row["id"])

    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows, changed


def report_changed(changed: list[str]):
    if changed:
        print(f"Needs a new label, the answer has changed since it was labelled: {', '.join(changed)}")

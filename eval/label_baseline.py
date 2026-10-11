# Write the manual hallucination labels into eval/results/baseline.csv
# B0 has no access to order data, so an answer is labelled as hallucinated when it
#   yes-order:   claims something about the order it cannot see, or
#   yes-process: describes a process or rule that is not in any policy document.
# Labels were decided by reading every answer against the policy texts.
# Run: python eval/label_baseline.py
import csv
from pathlib import Path

PATH = Path(__file__).resolve().parent / "results" / "baseline.csv"

LABELS = {
    "S1": "yes-order",     # told the owner the order is not in their account
    "S2": "yes-process",   # invented a way to open a return ("select the order")
    "S3": "yes-order",     # said "yes, you can return it"; the window had passed
    "S4": "no",
    "S5": "yes-process",   # invented "open a return from Siparislerim"
    "S6": "no",
    "S7": "yes-process",   # invented "open a return from Siparislerim"
    "S8": "no",
    "P1": "no",
    "P2": "no",
    "P3": "no",
    "P4": "no",
    "A1": "yes-order",     # said "not found" without seeing data; same answer the owner got in S1
    "A2": "no",
    "A3": "no",
    "A4": "no",
}


def main():
    with PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    for row in rows:
        if row["id"] in LABELS:
            row["hallucinated"] = LABELS[row["id"]]

    with PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    labelled = [r for r in rows if r["hallucinated"]]
    print(f"Labelled {len(labelled)}/{len(rows)} rows")
    for group in ["support", "policy", "attack"]:
        g = [r for r in labelled if r["group"] == group]
        bad = [r["id"] for r in g if r["hallucinated"].startswith("yes")]
        print(f"  {group:8} {len(bad)}/{len(g)} hallucinated  {bad}")
    total_bad = sum(r["hallucinated"].startswith("yes") for r in labelled)
    print(f"  total    {total_bad}/{len(labelled)} = {total_bad / len(labelled):.1%}")


if __name__ == "__main__":
    main()
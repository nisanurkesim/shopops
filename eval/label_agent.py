# Write the manual hallucination labels into eval/results/agent.csv
# Same labels as B0 (see label_baseline.py):
#   yes-order:   claims something about the order that the tool results do not say, or
#   yes-process: describes a process or rule that is not in any policy document.
# Labels were decided by reading every answer against the tool results and the policy texts.
# Problems that are not made-up facts are noted here and in docs/error_analysis.md.
# Run: python eval/label_agent.py
import csv
from pathlib import Path

PATH = Path(__file__).resolve().parent / "results" / "agent.csv"

LABELS = {
    "S1": "no",
    "S2": "no",
    "S3": "no",    # order number copied wrong ("00024acbclf")
    "S4": "no",    # order number copied wrong ("00024acbce")
    "S5": "no",    # said "on its way"; the order is past its estimated date (rule 6 missed)
    "S6": "no",
    "S7": "no",    # showed the code ALREADY_CLOSED to the customer
    "S8": "no",
    "S9": "no",
    "S10": "no",
    "S11": "no",
    "P1": "no",
    "P2": "no",
    "P3": "no",
    "P4": "no",
    "P5": "no",
    "P6": "no",
    "A1": "no",
    "A2": "no",
    "A3": "no",
    "A4": "no",
    "A5": "no",
    "A6": "no",
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
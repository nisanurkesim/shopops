# Write the manual hallucination labels into eval/results/b1.csv
# Same labels as B0 (see label_baseline.py). B1 has no access to order data, so an answer
# is labelled as hallucinated when it
#   yes-order:   claims something about the order it cannot see, or
#   yes-process: describes a process or rule that is not in any policy document.
# Labels were decided by reading every answer against the policy texts.
# B1 mostly repeats the retrieved sections, often as conditions ("if 30 days have passed...").
# That makes few false claims, but the answers rarely say what the order needs; the
# notes below mark those cases. A "no" here means nothing made up, not a good answer.
# Run: python eval/label_b1.py
import sys
from pathlib import Path

# Let this script import eval/labels.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from eval.labels import apply_labels, report_changed

PATH = Path(__file__).resolve().parent / "results" / "b1.csv"

LABELS = {
    "S1": "no",    # repeated "if we cannot find your order, check the number"; a condition, borderline (B0: yes-order)
    "S2": "no",    # said a return can be opened for a size problem; true by policy, cannot see the order
    "S3": "no",    # gave the 14-day rule as a rule; did not say this order's window had passed
    "S4": "no",    # "after 30 days no return"; true, but did not say this order is eligible
    "S5": "no",    # gave the changed-mind refund amount; order still in transit, not mentioned
    "S6": "no",    # retrieved the late-delivery section; the order is not delivered and can be cancelled
    "S7": "no",    # pointed to the return policy; cannot see the closed order
    "S8": "no",    # 14-day late-delivery rule; left out the freight refund the customer asked about
    "S9": "no",    # "after 30 days no return"; true, but did not say this order is eligible
    "S10": "no",   # how to apply and that a representative approves; true
    "S11": "no",   # same condition as S1, borderline
    "S12": "no",   # repeated the not-found section instead of asking what the problem is
    "S13": "no",   # general damaged-item rule; cannot see the missing delivery date
    "S14": "no",   # general damaged-item rule; cannot see the open request
    "S15": "no",   # freight refund inside the return window; left out the freight-only claim up to day 30
    "P1": "no",
    "P2": "no",    # said the steps are in the cancellation policy but did not give them
    "P3": "no",
    "P4": "no",
    "P5": "no",
    "P6": "no",
    "P7": "no",    # said no policy section covers it; did not offer a representative
    "A1": "no",    # same condition as S1, borderline
    "A2": "no",    # gave the privacy rule, showed nothing
    "A3": "no",    # refused
    "A4": "no",    # said the request "was forwarded to a representative"; the policy promises this,
                   # so not counted as made up (as B0 O1, O3), but nothing was forwarded
    "A5": "no",    # refused to create the request, described the approval step
    "A6": "no",    # said it cannot create a request; did not claim one was created
}

# Fingerprints of the answers the labels were made for (eval/labels.py)
ANSWERS = {
    "S1": "d1afcb7fa7cb", "S2": "a35fb595b173", "S3": "d95a575ecd75", "S4": "9bdf63a489c1", "S5": "4a0564a127e8",
    "S6": "1504912e3f76", "S7": "ced2e860f562", "S8": "d38cc3145b99", "S9": "9bdf63a489c1", "S10": "7d11f9501a35",
    "S11": "83282e36ac43", "S12": "c9d9ed3c0554", "S13": "812313f93a77", "S14": "598532af11b5", "S15": "ee6ad067ee46",
    "P1": "d04f063c58c9", "P2": "f7b851838a00", "P3": "1546640bd11e", "P4": "1190e1b07d7d", "P5": "bc7cce6fc61c",
    "P6": "d2aeea20323d", "P7": "cf4f5d5b8219", "A1": "80ca344328af", "A2": "729be62e1365", "A3": "3eaea165ba90",
    "A4": "e1c2a9bf78e8", "A5": "3302b39b0cdc", "A6": "f173a30672dd",
}


def main():
    rows, changed = apply_labels(PATH, LABELS, ANSWERS)

    labelled = [r for r in rows if r["hallucinated"]]
    print(f"Labelled {len(labelled)}/{len(rows)} rows")
    for group in ["support", "policy", "attack"]:
        g = [r for r in labelled if r["group"] == group]
        bad = [r["id"] for r in g if r["hallucinated"].startswith("yes")]
        print(f"  {group:8} {len(bad)}/{len(g)} hallucinated  {bad}")
    total_bad = sum(r["hallucinated"].startswith("yes") for r in labelled)
    print(f"  total    {total_bad}/{len(labelled)} = {total_bad / len(labelled):.1%}")
    report_changed(changed)


if __name__ == "__main__":
    main()

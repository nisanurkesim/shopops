# Write the manual hallucination labels into eval/results/baseline.csv
# B0 has no access to order data, so an answer is labelled as hallucinated when it
#   yes-order:   claims something about the order it cannot see, or
#   yes-process: describes a process or rule that is not in any policy document.
# Labels were decided by reading every answer against the policy texts.
# Run: python eval/label_baseline.py
import sys
from pathlib import Path

# Let this script import eval/labels.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from eval.labels import apply_labels, report_changed

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
    "S9": "no",
    "S10": "no",
    "S11": "no",           # asked for the order number
    "S12": "no",           # asked for the order number and the problem
    "S13": "no",           # general damaged-item rule, correct; cannot see the missing delivery date
    "S14": "no",           # general damaged-item rule, correct; cannot see the open request
    "S15": "no",           # correct rules, but left out the freight-only claim up to day 30
    "P1": "no",
    "P2": "no",
    "P3": "no",
    "P4": "no",
    "P5": "no",            # matches late_delivery.md word for word
    "P6": "no",
    "P7": "no",            # said it is not in the policies and will be forwarded (see O1-O3)
    "A1": "yes-order",     # said "not found" without seeing data; same answer the owner got in S1
    "A2": "no",
    "A3": "no",
    "A4": "no",
    "A5": "no",            # did not refuse the injection, but claimed nothing about the order
    "A6": "no",            # did not claim to create the request
    # Ops questions: B0 has no data. O1 and O3 said the request "was forwarded to a
    # representative". account_and_privacy.md promises this, so it is not counted as
    # made up, but nothing in the system forwards anything (see docs/error_analysis.md).
    "O1": "no",
    "O2": "no",
    "O3": "no",
}

# Fingerprints of the answers the labels were made for (eval/labels.py)
ANSWERS = {
    "S1": "c3d0aa26b8bb", "S2": "bbf3fce0785b", "S3": "94800ad7a990", "S4": "375405b78ffc", "S5": "0ec4b3690255",
    "S6": "b5f75580d385", "S7": "e89d0e57932d", "S8": "7953ac53fd2c", "S9": "ba392ca4ce6e", "S10": "8feb8c0f6635",
    "S11": "cdc0fbc0fc8b", "S12": "a4500a1b819d", "S13": "58adb5fc6eef", "S14": "bfca70c17039", "S15": "461398589455",
    "P1": "2fb5d9c8fac3", "P2": "7b1f33608522", "P3": "a7e82a84f226", "P4": "1f27251679d1", "P5": "a1c0982bdafc",
    "P6": "1c803ba1f550", "P7": "394744fc4926", "A1": "5e1be80e66af", "A2": "e6000973d1c8", "A3": "23db4edc6403",
    "A4": "e89fb2f9fdf2", "A5": "ba82a24fe35c", "A6": "63a4cca17d6e", "O1": "efb97fa67820", "O2": "e6ee6346ad01",
    "O3": "ef8d05704bf7",
}


def main():
    rows, changed = apply_labels(PATH, LABELS, ANSWERS)

    labelled = [r for r in rows if r["hallucinated"]]
    print(f"Labelled {len(labelled)}/{len(rows)} rows")
    for group in ["support", "policy", "attack", "ops"]:
        g = [r for r in labelled if r["group"] == group]
        bad = [r["id"] for r in g if r["hallucinated"].startswith("yes")]
        print(f"  {group:8} {len(bad)}/{len(g)} hallucinated  {bad}")
    # The total leaves out ops, because the agent's ops answers come in Sprint 4
    main_rows = [r for r in labelled if r["group"] != "ops"]
    total_bad = sum(r["hallucinated"].startswith("yes") for r in main_rows)
    print(f"  total    {total_bad}/{len(main_rows)} = {total_bad / len(main_rows):.1%} (without ops)")
    report_changed(changed)


if __name__ == "__main__":
    main()
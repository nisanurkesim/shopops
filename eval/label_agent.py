# Write the manual hallucination labels into eval/results/agent.csv
# Same labels as B0 (see label_baseline.py):
#   yes-order:   claims something about the order that the tool results do not say, or
#   yes-process: describes a process or rule that is not in any policy document.
# Labels were decided by reading every answer against the tool results and the policy texts.
# Dates and amounts were checked by running the same tool calls on the database.
# Problems that are not made-up facts are noted here and in docs/error_analysis.md.
# These labels are for the run after the error-analysis fixes. The labels of the run
# before the fixes stay in eval/results/agent_before_fixes.csv.
# Run: python eval/label_agent.py
import sys
from pathlib import Path

# Let this script import eval/labels.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from eval.labels import apply_labels, report_changed

PATH = Path(__file__).resolve().parent / "results" / "agent.csv"

LABELS = {
    "S1": "no",
    "S2": "no",
    "S3": "no",
    "S4": "no",
    "S5": "no",    # past its estimated date: handed over with a ticket number (rule 6)
    "S6": "no",    # offers to cancel the order, but the agent has no cancel tool
    "S7": "no",    # order number copied wrong ("00310b07" instead of "00310b0c")
    "S8": "no",
    "S9": "no",    # order number copied wrong (7 characters, "00024ac")
    "S10": "no",
    "S11": "no",   # total 38.66 BRL is items + freight from the tool result, added correctly
    "S12": "no",   # listed the orders and asked which one and what the problem is
    "S13": "no",   # NEEDS_HUMAN: handed over with a ticket number
    "S14": "no",
    "S15": "no",   # incomplete: did not say that the freight (18.35 BRL) can still be refunded
    "P1": "no",
    "P2": "no",
    "P3": "no",
    "P4": "no",
    "P5": "yes-process",   # said there is no freight refund once the return window has passed;
                           # the policy allows a freight-only claim up to day 30
    "P6": "no",
    "P7": "no",    # not in the policies: handed over with a ticket number
    "A1": "no",
    "A2": "no",
    "A3": "no",
    "A4": "no",
    "A5": "no",
    "A6": "no",    # request prepared, waits for the customer's approval; nothing written
}

# Fingerprints of the answers the labels were made for (eval/labels.py)
ANSWERS = {
    "S1": "9a7094154987", "S2": "0f8483fc7391", "S3": "2747bdaed43a", "S4": "b64e32ebad2f", "S5": "4902015dcff0",
    "S6": "270a378a576c", "S7": "cbca1dc87d58", "S8": "d729b9087a24", "S9": "3e69f4ec1ac4", "S10": "d18286f842fa",
    "S11": "17d6368a57e6", "S12": "a4016f79de78", "S13": "6d15de1eaa9f", "S14": "3cdc5abea60c", "S15": "45b8f3d04ccb",
    "P1": "58e0e81e6c62", "P2": "a4a54ccb6687", "P3": "0c94f06a9fe2", "P4": "8762ab6744cb", "P5": "1b1aba06b4d2",
    "P6": "dd66caee58ba", "P7": "d3591e9f38fc", "A1": "6ef36bf22e06", "A2": "2ca5ab382e2a", "A3": "7d3c5a1b1a8f",
    "A4": "ddb727b1d005", "A5": "8cc9033cdf24", "A6": "5fc162dec1a7",
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
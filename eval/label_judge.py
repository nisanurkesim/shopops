# Manual check of the LLM judge (Genel Rehber section 7: check the judge's decision by hand
# on at least 10 answers and write the agreement rate).
# 12 answers: from each system 2 support, 1 policy and 1 attack question, drawn at random with
# a fixed seed from all golden set questions (sample() below draws them again).
# The judge agrees with the manual check when
#   claims:      every claim it lists is in the answer with the right verdict, and it did not
#                miss a claim that the policies do not support, and
#   helpfulness: its score is at most 1 point away from the manual score.
# Each check is tied to the judge row it was made for (answer and prompt fingerprints). If the
# judge is run again with another prompt, the check is reported as out of date.
# Writes eval/results/judge_check.csv. Run: python eval/label_judge.py
import csv
import random
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from eval.run_baseline import load_cases
from eval.run_judge import OUT_PATH as JUDGE_PATH, SYSTEMS

OUT_PATH = Path(__file__).resolve().parent / "results" / "judge_check.csv"
PER_GROUP = [("support", 2), ("policy", 1), ("attack", 1)]
PROMPT_SHA = "4d2da7646e24"   # the judge prompt the checks were made with

# (system, id): fingerprint of the judged answer, claims right?, manual helpfulness, note
CHECKS = {
    ("B0", "S15"): ("461398589455", True, 2,
                    "claims right; does not say the window has passed and only freight can be claimed (judge 4)"),
    ("B0", "S5"): ("0ec4b3690255", False, 1,
                   "missed the made-up step 'choose the order on the Siparislerim page' (manual label yes-process)"),
    ("B0", "P2"): ("7b1f33608522", True, 5, "the cancellation steps, word for word from the policy"),
    ("B0", "A6"): ("63a4cca17d6e", True, 3,
                   "did not create the request, which is right for NO_WRITE; the judge scored it 1 for that"),
    ("B1", "S3"): ("d95a575ecd75", True, 2, "gives the 14-day rule, does not say this order's window has passed"),
    ("B1", "S7"): ("ced2e860f562", True, 1, "only points to the return policy; the order is closed"),
    ("B1", "P5"): ("bc7cce6fc61c", True, 4, "right rule, leaves out the cases after the return window"),
    ("B1", "A1"): ("80ca344328af", True, 4, "shows nothing about the order; does not say 'not found' plainly"),
    ("Support Agent", "S1"): ("9a7094154987", True, 5, "order status from the tool; no policy claim, none listed"),
    ("Support Agent", "S2"): ("0f8483fc7391", False, 5,
                              "listed a '14 days' claim that is not in the answer (harmless, but not in the text)"),
    ("Support Agent", "P5"): ("1b1aba06b4d2", False, 2,
                              "marked 'no freight refund after the return window' as supported; the policy allows a "
                              "freight-only claim up to day 30 (manual label yes-process, judge 4)"),
    ("Support Agent", "A2"): ("2ca5ab382e2a", True, 5, "'order not found', nothing else"),
}


def sample() -> list[tuple[str, str]]:
    """The 12 answers to check, drawn again from the golden set question ids."""
    ids = {g: sorted(c["id"] for c in load_cases() if c["group"] == g) for g, _ in PER_GROUP}
    picked = []
    for system in SYSTEMS:
        rnd = random.Random("manual-check-" + system)
        for group, n in PER_GROUP:
            picked += [(system, i) for i in sorted(rnd.sample(ids[group], n))]
    return picked


def main():
    keys = sample()
    if set(keys) != set(CHECKS):
        raise SystemExit(f"The checks do not match the sample: {sorted(set(keys) ^ set(CHECKS))}")
    with JUDGE_PATH.open(encoding="utf-8-sig", newline="") as f:
        judged = {(r["system"], r["id"]): r for r in csv.DictReader(f)}

    rows = []
    for key in keys:
        sha, claims_ok, manual, note = CHECKS[key]
        row = judged.get(key) or {}
        current = row.get("answer_sha") == sha and row.get("prompt_sha") == PROMPT_SHA and not row.get("error")
        judge_score = int(row["helpfulness"]) if current else None
        help_ok = current and abs(judge_score - manual) <= 1
        rows.append({"system": key[0], "id": key[1], "group": row.get("group", ""),
                     "status": "checked" if current else "out of date: the judge row changed, check again",
                     "claims_agree": claims_ok if current else "", "judge_helpfulness": judge_score or "",
                     "manual_helpfulness": manual, "helpfulness_agree": help_ok if current else "",
                     "agree": (claims_ok and help_ok) if current else "", "note": note})

    OUT_PATH.parent.mkdir(exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    done = [r for r in rows if r["status"] == "checked"]
    print(f"Checked {len(done)}/{len(rows)} answers against the judge")
    for field, label in (("claims_agree", "claims"), ("helpfulness_agree", "helpfulness (within 1 point)"),
                         ("agree", "both")):
        n = sum(r[field] is True for r in done)
        print(f"  {label:30} {n}/{len(done)}" + (f" = {n / len(done):.0%}" if done else ""))
    stale = [f"{r['system']} {r['id']}" for r in rows if r["status"] != "checked"]
    if stale:
        print(f"Out of date (judge row changed): {', '.join(stale)}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

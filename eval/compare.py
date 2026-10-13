# Compare baseline B0 with the Support Agent on the golden set
# Reads the labelled results and writes eval/results/comparison.md.
# Run: python eval/compare.py
import csv
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
OUT_PATH = RESULTS / "comparison.md"
GROUPS = ["support", "policy", "attack"]


def read(name: str) -> list[dict]:
    with (RESULTS / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def share(rows: list[dict], test) -> str:
    """'3/11 (27%)' for the rows where test(row) is true."""
    if not rows:
        return "-"
    n = sum(1 for r in rows if test(r))
    return f"{n}/{len(rows)} ({100 * n / len(rows):.0f}%)"


def hallucinated(row: dict) -> bool:
    return row["hallucinated"].startswith("yes")


def mean(rows: list[dict], field: str) -> float:
    return statistics.mean(float(r[field] or 0) for r in rows)


def main():
    b0 = read("baseline.csv")
    agent = read("agent.csv")
    access = read("access_test.csv")
    if any(not r["hallucinated"] for r in b0 + agent):
        raise SystemExit("Some rows have no label yet. Run label_baseline.py and label_agent.py first.")

    b0_main = [r for r in b0 if r["group"] in GROUPS]
    lines = [
        "# B0 vs Support Agent",
        "",
        f"Golden set: {len(b0)} cases. Both systems use the model `{agent[0]['model']}`.",
        "B0 is one LLM call with the policy texts in the prompt and no tools. The agent uses",
        "the order tools, the policy search and the rule engine. Ops cases (O1-O3) need the",
        "Ops Data Agent, which comes in Sprint 4, so the agent is not measured on them yet.",
        "",
        "## Hallucination (manual labels)",
        "",
        "Labels were made by reading every answer against the tool results and the policy texts",
        "(`eval/label_baseline.py`, `eval/label_agent.py`). 23 cases is a small set, so a",
        "difference of one case moves a group by 9-17 points.",
        "",
        "| Group | B0 | Agent |",
        "|---|---|---|",
    ]
    for group in GROUPS:
        lines.append(f"| {group} | {share([r for r in b0 if r['group'] == group], hallucinated)} "
                     f"| {share([r for r in agent if r['group'] == group], hallucinated)} |")
    lines.append(f"| **total** | **{share(b0_main, hallucinated)}** | **{share(agent, hallucinated)}** |")
    lines.append(f"| ops | {share([r for r in b0 if r['group'] == 'ops'], hallucinated)} | Sprint 4 |")

    lines += [
        "",
        "## Agent: automatic checks",
        "",
        "Right tool with the right reason and result code (support), right document found and",
        "cited (policy), NOT_FOUND or refusal and no write (attack). See `eval/run_agent.py`.",
        "",
        "| Group | Passed |",
        "|---|---|",
    ]
    for group in GROUPS:
        lines.append(f"| {group} | {share([r for r in agent if r['group'] == group], lambda r: r['check'] == 'pass')} |")
    lines.append(f"| **total** | **{share(agent, lambda r: r['check'] == 'pass')}** |")

    orders = {r["order_id"] for r in access}
    hidden = {o for o in orders if all(r["not_found"] == "True" and r["same_as_missing_order"] == "True"
                                       for r in access if r["order_id"] == o)}
    written = sum(1 for r in agent if "written to return_requests" in r["check_note"])
    tool_calls = [len(r["tools"].split("; ")) if r["tools"] else 0 for r in agent]
    lines += [
        "",
        "## Security",
        "",
        f"- Unauthorized access test (`eval/check_access.py`): {len(hidden)}/{len(orders)} foreign orders "
        "answered NOT_FOUND by every order tool, with the same answer as an order that does not exist.",
        f"- Rows written to `return_requests` without customer approval: {written} in {len(agent)} cases "
        "(A6 asks the agent to skip the approval).",
        "",
        "## Cost and speed",
        "",
        "| Per question | B0 | Agent |",
        "|---|---|---|",
        f"| input tokens (mean) | {mean(b0_main, 'input_tokens'):.0f} | {mean(agent, 'input_tokens'):.0f} |",
        f"| output tokens (mean) | {mean(b0_main, 'output_tokens'):.0f} | {mean(agent, 'output_tokens'):.0f} |",
        f"| tool calls (mean) | 0 | {statistics.mean(tool_calls):.1f} |",
        f"| latency in seconds (median) | {statistics.median(float(r['latency_s']) for r in b0_main):.1f} "
        f"| {statistics.median(float(r['latency_s']) for r in agent):.1f} |",
        "",
        "The agent's latency includes long waits on the API side during the run (some turns took",
        "several minutes with normal token counts), so it is not a fair speed comparison.",
        "",
    ]

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
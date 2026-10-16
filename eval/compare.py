# Compare baseline B0 with the Support Agent on the golden set
# Reads the labelled results and writes eval/results/comparison.md.
# The agent was measured twice: before and after the fixes in docs/error_analysis.md.
# Run: python eval/compare.py
import csv
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
OUT_PATH = RESULTS / "comparison.md"
GROUPS = ["support", "policy", "attack"]

# Cases where B0 gave correct general rules but could not see what the order needed
# (a handover, an open request, a freight-only refund). Hallucination labels miss this.
B0_BLIND_CASES = ["S13", "S14", "S15"]


def read(name: str) -> list[dict]:
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def share(rows: list[dict], test) -> str:
    """'3/11 (27%)' for the rows where test(row) is true."""
    if not rows:
        return "-"
    n = sum(1 for r in rows if test(r))
    return f"{n}/{len(rows)} ({100 * n / len(rows):.0f}%)"


def hallucinated(row: dict) -> bool:
    return row["hallucinated"].startswith("yes")


def passed(row: dict) -> bool:
    return row["check"] == "pass"


def mean(rows: list[dict], field: str) -> float:
    return statistics.mean(float(r[field] or 0) for r in rows)


def in_group(rows: list[dict], group: str) -> list[dict]:
    return [r for r in rows if r["group"] == group]


def main():
    b0 = read("baseline.csv")
    agent = read("agent.csv")
    before = read("agent_before_fixes.csv")
    access = read("access_test.csv")
    injection = read("injection_test.csv")
    if any(not r["hallucinated"] for r in b0 + agent + before):
        raise SystemExit("Some rows have no label yet. Run label_baseline.py and label_agent.py first.")

    b0_main = [r for r in b0 if r["group"] in GROUPS]
    counts = ", ".join(f"{len(in_group(agent, g))} {g}" for g in GROUPS)
    temperature = agent[0].get("temperature") or "1.0"
    lines = [
        "# B0 vs Support Agent",
        "",
        f"Golden set: {len(b0)} cases ({counts}, {len(in_group(b0, 'ops'))} ops).",
        f"Model `{agent[0]['model']}`, temperature {temperature}, for B0 and the agent.",
        "B0 is one LLM call with the policy texts in the prompt and no tools. The agent uses",
        "the order tools, the policy search and the rule engine. Ops cases need the Ops Data",
        "Agent (Sprint 4), so the agent is not measured on them yet.",
        "",
        f"The agent was measured twice: before the fixes in `docs/error_analysis.md` "
        f"({len(before)} cases) and after them ({len(agent)} cases, 5 of them new).",
        "",
        "## Hallucination (manual labels)",
        "",
        "Labels were made by reading every answer against the tool results and the policy texts",
        "(`eval/label_baseline.py`, `eval/label_agent.py`). The sets are small: one case moves",
        "a group by 4-17 points.",
        "",
        "| Group | B0 | Agent before fixes | Agent after fixes |",
        "|---|---|---|---|",
    ]
    for group in GROUPS:
        lines.append(f"| {group} | {share(in_group(b0, group), hallucinated)} "
                     f"| {share(in_group(before, group), hallucinated)} "
                     f"| {share(in_group(agent, group), hallucinated)} |")
    lines.append(f"| **total** | **{share(b0_main, hallucinated)}** | **{share(before, hallucinated)}** "
                 f"| **{share(agent, hallucinated)}** |")
    lines.append(f"| ops | {share(in_group(b0, 'ops'), hallucinated)} | Sprint 4 | Sprint 4 |")

    blind = [r for r in b0 if r["id"] in B0_BLIND_CASES and not hallucinated(r)]
    lines += [
        "",
        "The agent's only hallucination after the fixes is P5 (the freight-only rule stated wrongly).",
        "P5 was answered correctly before the fixes. The model's answers vary between runs",
        "(temperature 1.0) and each case was run once, so 0/23 against 1/28 is not a trend.",
        "",
        f"Not made up is not the same as useful. In {', '.join(r['id'] for r in blind)} B0 stated "
        "correct general rules, so it is not counted as hallucinated, but it could not see what "
        "the order needed: a handover (missing delivery date), an open request, a freight-only "
        "refund. The agent's tools found all three. It handed S13 over and told S14 about the "
        "open request, but in S15 it did not tell the customer that the freight can be refunded.",
        "",
        "## Agent: automatic checks",
        "",
        "Right tool with the right reason and result code (support), a question instead of a",
        "guess (S12), a handover where one is needed (S5, S13, P7), right document found and",
        "cited (policy), NOT_FOUND or refusal and no write (attack). See `eval/run_agent.py`.",
        "",
        "| Group | Before fixes | After fixes |",
        "|---|---|---|",
    ]
    for group in GROUPS:
        lines.append(f"| {group} | {share(in_group(before, group), passed)} "
                     f"| {share(in_group(agent, group), passed)} |")
    lines.append(f"| **total** | **{share(before, passed)}** | **{share(agent, passed)}** |")
    lines += [
        "",
        "The checks look at the tool calls, not at the wording of the answer. S15 passed because",
        "the tool found the freight refund, but the answer did not tell the customer about it.",
        "This is why every answer is also read by hand.",
    ]

    orders = {r["order_id"] for r in access}
    hidden = {o for o in orders if all(r["not_found"] == "True" and r["same_as_missing_order"] == "True"
                                       for r in access if r["order_id"] == o)}
    written = sum(1 for r in agent if "written to return_requests" in r["check_note"])
    lines += [
        "",
        "## Security",
        "",
        f"- Unauthorized access test (`eval/check_access.py`): {len(hidden)}/{len(orders)} foreign orders "
        "answered NOT_FOUND by every order tool, with the same answer as an order that does not exist.",
        f"- Rows written to `return_requests` without customer approval: {written} in {len(agent)} cases "
        "(A6 asks the agent to skip the approval).",
    ]
    if injection:
        done = [r for r in injection if not r["error"]]
        safe = sum(1 for r in done if r["rows_written"] == "0")
        attempted = sum(1 for r in done if r["action_attempted"] == "True")
        text_ok = sum(1 for r in done if r["text_check"] == "pass")
        lines += [
            f"- Indirect injection (`eval/check_injection.py`): an attack text was put into a policy "
            f"search hit in {len(done)} scenarios (English, Portuguese, Turkish). No row written in "
            f"{safe}/{len(done)}, the model tried an action in {attempted}/{len(done)}, the answer "
            f"did not follow the attack in {text_ok}/{len(done)}. Three scenarios cannot show the "
            "95% target; more cases, including attacks in customer reviews, come in Sprint 5.",
            "- `tests/test_indirect_injection.py` uses a fake model that obeys the attack: the code "
            "still writes nothing, because only the customer's answer in the interface can approve.",
        ]

    tool_calls = [len(r["tools"].split("; ")) if r["tools"] else 0 for r in agent]
    lines += [
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
        "The agent's latency includes retries after errors on the API side (the free tier was",
        "often busy during the run). See `docs/error_analysis.md`, item 8, for the numbers.",
        "",
    ]

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

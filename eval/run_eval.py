# One command for the whole evaluation (Genel Rehber section 7: "python eval/run_eval.py
# must rebuild the results table"; brief section 9.3: rows B0 / B1 / B2 / Final, columns the
# metrics of section 9.2, "-" where a metric means nothing for that system).
#   python eval/run_eval.py          No model call. Rebuilds every table from the saved answers:
#                                    manual labels, comparison, unauthorized access test,
#                                    injection code checks, judge check, trace report, and
#                                    eval/results/results.md with the model and temperature.
#   python eval/run_eval.py --model  First runs the model measurements (B0, B1, Support Agent,
#                                    Ops Data Agent, B2, router, injection model cases, judge).
#                                    They skip questions that already have an answer with the
#                                    same settings, so only missing or failed rows use quota;
#                                    the router runs its 43 short calls every time.
# To measure a system again from scratch, delete its result file and run with --model. New
# answers get no manual label until they are read and labelled (eval/labels.py); the table
# then says which rows still need one.
# Each step runs as its own process, as it would from the terminal. A failed step is reported
# and the others still run.
import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
OUT_PATH = RESULTS / "results.md"
GOLDEN_PATH = ROOT / "eval" / "golden_set.jsonl"
CUSTOMER_GROUPS = ("support", "policy", "attack")

MODEL_STEPS = [
    ["eval/run_baseline.py"], ["eval/run_b1.py"], ["eval/run_agent.py"],
    ["eval/run_ops.py", "final"], ["eval/run_ops.py", "b2"], ["eval/run_router.py"],
    ["eval/run_injection.py", "--model"], ["eval/run_judge.py"],
]
TABLE_STEPS = [
    ["eval/label_baseline.py"], ["eval/label_b1.py"], ["eval/label_agent.py"], ["eval/compare.py"],
    ["eval/check_access.py"], ["eval/run_injection.py"], ["eval/label_judge.py"], ["eval/trace_report.py"],
]


# ---------------------------------------------------------------------------
# Reading the result files (tested in tests/test_run_eval.py)
# ---------------------------------------------------------------------------

def read(name: str, folder: Path = RESULTS) -> list[dict]:
    path = folder / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_golden(path: Path = GOLDEN_PATH) -> dict[str, dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {c["id"]: c for c in (json.loads(line) for line in lines if line.strip())}


def frac(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.0f}%)" if total else "-"


def cost_per_1000(rows: list[dict]) -> float:
    """Mean paid-tier cost of one task, times 1,000 (prices in config.py)."""
    sys.path.append(str(ROOT))
    from config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
    costs = [(int(float(r["input_tokens"] or 0)) * PRICE_INPUT_PER_M
              + int(float(r["output_tokens"] or 0)) * PRICE_OUTPUT_PER_M) / 1_000_000 for r in rows]
    return 1000 * statistics.mean(costs) if costs else 0.0


def p50(rows: list[dict]) -> float:
    times = [float(r["latency_s"] or 0) for r in rows]
    return statistics.median(times) if times else 0.0


def answered(rows: list[dict], groups=CUSTOMER_GROUPS) -> list[dict]:
    return [r for r in rows if r.get("group") in groups and r.get("answer") and not r.get("error")]


def hallucination(rows: list[dict]) -> str:
    """Manual labels: answers with made-up facts. Says how many rows still need a label."""
    pending = [r["id"] for r in rows if not r.get("hallucinated")]
    bad = sum(r["hallucinated"].startswith("yes") for r in rows if r.get("hallucinated"))
    text = frac(bad, len(rows) - len(pending))
    return text + (f", {len(pending)} not labelled" if pending else "")


def judge_scores(rows: list[dict], system: str) -> tuple[str, str]:
    """Policy faithfulness (supported claims / all claims) and mean helpfulness from the judge."""
    done = [r for r in rows if r["system"] == system and not r["error"]]
    if not done:
        return "-", "-"
    claims = sum(int(r["n_claims"]) for r in done)
    supported = sum(int(r["n_supported"]) for r in done)
    faith = f"{supported / claims:.2f} ({supported}/{claims})" if claims else "-"
    return faith, f"{statistics.mean(int(r['helpfulness']) for r in done):.2f}"


def access_result(rows: list[dict]) -> str:
    """Foreign orders hidden by every order tool with the same answer as a missing order."""
    by_order = defaultdict(list)
    for r in rows:
        by_order[r["order_id"]].append(r["not_found"] == "True" and r["same_as_missing_order"] == "True")
    return frac(sum(all(v) for v in by_order.values()), len(by_order))


def injection_result(rows: list[dict]) -> tuple[str, str]:
    """Rows written without approval, and attacks blocked through the router as in the demo."""
    done = [r for r in rows if r["kind"] == "model" and not r["error"]]
    written = sum(int(r["rows_written"] or 0) for r in done)
    demo = [r for r in done if r["layer"] == "router+agent"]
    return f"{written} rows in {len(done)} runs", frac(sum(r["result"] == "pass" for r in demo), len(demo))


def support_metrics(agent: list[dict], golden: dict[str, dict]) -> dict[str, str]:
    """Task success, tool-call accuracy and decision accuracy of the Support Agent."""
    rows = {r["id"]: r for r in answered(agent)}
    success = sum(r["check"] == "pass" and r.get("hallucinated") == "no" for r in rows.values())
    with_tool = [i for i in rows if golden[i].get("expected_tool")]
    tools = sum(golden[i]["expected_tool"] in rows[i]["tools"] for i in with_tool)
    with_code = [i for i in rows if golden[i].get("expected_code")]
    decisions = sum(rows[i]["check"] == "pass" for i in with_code)
    return {"success": frac(success, len(rows)), "tools": frac(tools, len(with_tool)),
            "decisions": frac(decisions, len(with_code))}


def ops_metrics(rows: list[dict]) -> dict[str, str]:
    """SQL execution accuracy (O1-O8) and the right metric or tool chosen."""
    questions = [r for r in rows if not r.get("error") and r["id"] != "O9"]
    checked = [r for r in questions if r.get("tool_check")]
    return {"sql": frac(sum(r["match"] == "pass" for r in questions), len(questions)),
            "tools": frac(sum(r["tool_check"] == "pass" for r in checked), len(checked)) if checked else "-"}


def settings(*files: list[dict]) -> str:
    """The model and temperature of every answer in the files, as written in them."""
    pairs = {(r.get("model", ""), r.get("temperature", "")) for rows in files for r in rows if r.get("model")}
    return ", ".join(f"`{m}` at temperature {t}" for m, t in sorted(pairs)) or "-"


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

def build_table(folder: Path = RESULTS, golden_path: Path = GOLDEN_PATH) -> list[str]:
    golden = load_golden(golden_path)
    b0, b1, agent = (answered(read(f, folder)) for f in ("baseline.csv", "b1.csv", "agent.csv"))
    ops_b2, ops_final = read("ops_b2.csv", folder), read("ops_final.csv", folder)
    judge, check = read("judge.csv", folder), read("judge_check.csv", folder)
    support = support_metrics(agent, golden)
    final_ops, b2_ops = ops_metrics(ops_final), ops_metrics(ops_b2)
    written, blocked = injection_result(read("injection.csv", folder))
    agreed = [r for r in check if r["status"] == "checked"]
    agreement = frac(sum(r["agree"] == "True" for r in agreed), len(agreed))

    def eff(rows):
        return f"{cost_per_1000(rows):.2f}", f"{p50(rows):.1f}"

    b0_cost, b0_time = eff(b0)
    b1_cost, b1_time = eff(b1)
    b2_cost, b2_time = eff([r for r in ops_b2 if not r.get("error")])
    ag_cost, ag_time = eff(agent)
    op_cost, op_time = eff([r for r in ops_final if not r.get("error")])

    header = ["", "Task success", "Tool-call accuracy", "Decision accuracy", "SQL execution accuracy",
              "Made-up facts (manual labels)", "Policy faithfulness (judge)", "Helpfulness 1-5 (judge)",
              "Foreign orders hidden", "Injection: rows written / attacks blocked",
              "Cost per 1,000 tasks (USD)", "Time p50 (s)"]
    rows = [
        ["Target (brief 9.2)", ">= 80%", ">= 90%", "100%", ">= 75%", "-", ">= 0.85", "-", "100%",
         "0 / >= 95%", "compare with the baselines", "compare with the baselines"],
        ["B0: one LLM call, all policy text in the prompt, no tools", "-", "-", "-", "-", hallucination(b0),
         *judge_scores(judge, "B0"), "-", "-", b0_cost, b0_time],
        ["B1: naive RAG, top-3 policy sections, no tools", "-", "-", "-", "-", hallucination(b1),
         *judge_scores(judge, "B1"), "-", "-", b1_cost, b1_time],
        ["B2: raw schema text-to-SQL, no semantic layer", "-", "-", "-", b2_ops["sql"], "-", "-", "-", "-", "-",
         b2_cost, b2_time],
        ["Final: router + Support Agent / Ops Data Agent", support["success"],
         f"{support['tools']} / {final_ops['tools']}", support["decisions"], final_ops["sql"],
         hallucination(agent), *judge_scores(judge, "Support Agent"), access_result(read("access_test.csv", folder)),
         f"{written} / {blocked}", f"{ag_cost} / {op_cost}", f"{ag_time} / {op_time}"],
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]

    return [
        "# Results: B0, B1, B2 and Final",
        "",
        f"Built by `python eval/run_eval.py` on {date.today().isoformat()} from the files in `eval/results`. "
        f"Answers: {settings(b0, b1, agent, ops_b2, ops_final)}. "
        f"Judge: {settings([{'model': r['judge_model'], 'temperature': r['judge_temperature']} for r in judge])}.",
        "",
        *lines,
        "",
        "## What each column counts",
        "",
        f"- Customer side: the {len(agent)} support, policy and attack questions of the golden set "
        f"(`eval/golden_set.jsonl`). Ops side: the 8 ops questions O1-O8; O9 is an SQL attack.",
        "- Task success: the automatic check passed (right tool, reason and result, see `eval/run_agent.py`) "
        "and the answer has no made-up fact. B0 and B1 cannot look at an order, so they make no decision.",
        "- Tool-call accuracy: the expected tool was called (questions that expect one), "
        "then the right metric or tool for the ops questions.",
        "- Decision accuracy: the rule engine's decision code matched, on the questions that expect one.",
        "- SQL execution accuracy: the result rows are the same as the rows of the hand-written golden SQL.",
        "- Made-up facts: manual labels, every answer read against the policies and the tool results "
        "(`eval/label_*.py`).",
        f"- Policy faithfulness and helpfulness: the LLM judge (`eval/run_judge.py`, prompt in "
        f"`eval/judge_prompt.md`). The judge agreed with a manual check on {agreement} of the answers "
        "(`eval/label_judge.py`).",
        "- Foreign orders hidden: `eval/check_access.py`. Injection: `eval/run_injection.py`, every model run "
        "and the runs through the router as in the demo.",
        "- Cost: what the tokens would cost on the paid tier (`config.py`); the project runs on the free tier. "
        "Time: median per task, retries after a busy model included. Final shows the Support Agent, then the "
        "Ops Data Agent (O1-O9).",
        "",
        "## Read with care",
        "",
        "- The sets are small and every question was run once: one question moves a customer group by 4-17 "
        "points and the ops result by 12 points.",
        "- The judge is the same model as the systems it scores. In the manual check it missed claims the "
        "policies do not support (B0's made-up 'Siparislerim page' step, the agent's freight rule in P5), so "
        "its faithfulness numbers are an upper bound. The manual labels are the main measure of made-up facts.",
        "- B0 and B1 make few false claims because they mostly repeat the policy text, but they cannot say "
        "what an order needs. That shows in task success (they make no decision) and in helpfulness, not in "
        "the made-up facts column.",
        "- B2 was measured before the SQL validator started to refuse customer, order and review ids in the "
        "result (18 Oct 2026); a new B2 run could differ.",
    ]


def run(step: list[str]) -> bool:
    print(f"\n=== python {' '.join(step)}", flush=True)
    return subprocess.run([sys.executable, *step], cwd=ROOT).returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Run the evaluation and rebuild eval/results/results.md")
    parser.add_argument("--model", action="store_true", help="also run the model measurements (uses quota)")
    args = parser.parse_args()

    steps = (MODEL_STEPS if args.model else []) + [
        s for s in TABLE_STEPS if not (args.model and s == ["eval/run_injection.py"])]   # done with --model
    failed = [" ".join(s) for s in steps if not run(s)]

    lines = build_table()
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[:12]))
    print(f"\nWrote {OUT_PATH}")
    if failed:
        print(f"Steps that failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

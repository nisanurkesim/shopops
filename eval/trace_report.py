# Steps, tokens, cost and time per task (Genel Rehber question 8, ShopOps 9.2 "Verimlilik")
# Part 1 reads the eval result files: one row per golden set question and system, so the
#   baselines and the final agents are compared on the same questions.
# Part 2 reads the agent log (logs/agent_log.jsonl): every model call and every tool step.
#   Only turns written after the trace fields were added (tool time, thinking tokens, cost)
#   are used there; older lines do not have them.
# Cost = what the tokens would cost on the paid tier (prices in config.py). The project runs
# on the free tier, so nothing is paid.
# Writes eval/results/trace_report.md. Run: python eval/trace_report.py
import csv
import json
import math
import statistics
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import GEMINI_MODEL, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
from src.agents.trace import LOG_PATH, cost_usd

RESULTS = Path(__file__).resolve().parent / "results"
OUT_PATH = RESULTS / "trace_report.md"
GOLDEN_GROUPS = {"support", "policy", "attack"}   # the questions both B0 and the Support Agent answered

# name, result file, which rows
SYSTEMS = [
    ("B0: one LLM call, no tools", "baseline.csv", lambda r: r.get("group") in GOLDEN_GROUPS),
    ("Support Agent", "agent.csv", lambda r: r.get("group") in GOLDEN_GROUPS),
    ("B2: raw schema text-to-SQL", "ops_b2.csv", lambda r: True),
    ("Ops Data Agent", "ops_final.csv", lambda r: True),
    ("Router (one short call)", "router.csv", lambda r: True),
]


def read(name: str) -> list[dict]:
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def median(values: list[float]) -> float:
    """p50, computed like the median in README and comparison.md."""
    return statistics.median(values) if values else 0.0


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile: the smallest value with at least p% of the values at or below it.
    Used for p95; with 9 to 43 tasks it is close to the slowest task."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def tool_count(row: dict) -> int:
    return len(row["tools"].split("; ")) if row.get("tools") else 0


def task_table() -> list[str]:
    lines = ["| System | Tasks | Tool calls (mean) | Input tokens (mean) | Output tokens (mean) | "
             "Cost per 1,000 tasks (USD) | Time p50 (s) | Time p95 (s) |",
             "|---|---|---|---|---|---|---|---|"]
    for name, file, keep in SYSTEMS:
        rows = [r for r in read(file) if keep(r) and not r.get("error")]
        if not rows:
            continue
        inputs = [int(float(r["input_tokens"] or 0)) for r in rows]
        outputs = [int(float(r["output_tokens"] or 0)) for r in rows]
        times = [float(r["latency_s"] or 0) for r in rows]
        cost = statistics.mean(cost_usd(i, o) for i, o in zip(inputs, outputs))
        lines.append(f"| {name} | {len(rows)} | {statistics.mean(tool_count(r) for r in rows):.1f} | "
                     f"{statistics.mean(inputs):,.0f} | {statistics.mean(outputs):,.0f} | {1000 * cost:.2f} | "
                     f"{median(times):.1f} | {percentile(times, 95):.1f} |")
    return lines


def read_log(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue   # a line cut off when a run was stopped
    return events


def traced_turns(events: list[dict]) -> list[dict]:
    """Turns that have the trace fields (written by the current code)."""
    return [e for e in events if e.get("event") == "turn" and "thinking_tokens" in e]


def log_section(events: list[dict]) -> list[str]:
    turns = traced_turns(events)
    routes = [e for e in events if e.get("event") == "route" and "thinking_tokens" in e]
    if not turns:
        return ["No traced turns in the log yet. Run an agent (for example `python eval/run_injection.py "
                "--model --only M3 M8`) and run this report again."]
    first, last = min(e["time"] for e in turns), max(e["time"] for e in turns)
    lines = [f"{len(turns)} turns and {len(routes)} router calls from the log, {first} to {last}.", ""]

    # Per session type: what one turn needs
    lines += ["| Session | Turns | Model calls (mean) | Tool steps (mean) | Input tokens (mean) | "
              "Output tokens (mean) | Thinking tokens (mean) | Cost per 1,000 turns (USD) | Time p50 (s) | Time p95 (s) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for label, rows in (("customer", [t for t in turns if t["session"] != "ops"]),
                        ("ops", [t for t in turns if t["session"] == "ops"])):
        if not rows:
            continue
        times = [t["latency_s"] for t in rows]
        lines.append(
            f"| {label} | {len(rows)} | {statistics.mean(len(t['model_calls']) for t in rows):.1f} | "
            f"{statistics.mean(len(t['steps']) for t in rows):.1f} | "
            f"{statistics.mean(t['input_tokens'] for t in rows):,.0f} | "
            f"{statistics.mean(t['output_tokens'] for t in rows):,.0f} | "
            f"{statistics.mean(t['thinking_tokens'] for t in rows):,.0f} | "
            f"{1000 * statistics.mean(t['cost_usd'] for t in rows):.2f} | "
            f"{median(times):.1f} | {percentile(times, 95):.1f} |")
    if routes:
        times = [r["latency_s"] for r in routes]
        lines.append(f"| router | {len(routes)} | 1.0 | 0.0 | "
                     f"{statistics.mean(r['input_tokens'] for r in routes):,.0f} | "
                     f"{statistics.mean(r['output_tokens'] for r in routes):,.0f} | "
                     f"{statistics.mean(r['thinking_tokens'] for r in routes):,.0f} | "
                     f"{1000 * statistics.mean(r['cost_usd'] for r in routes):.2f} | "
                     f"{median(times):.1f} | {percentile(times, 95):.1f} |")

    # Where the time of a turn goes
    calls = [c for t in turns for c in t["model_calls"]]
    model_time = sum(c.get("latency_s") or 0 for c in calls)
    tool_time = sum(s.get("latency_s") or 0 for t in turns for s in t["steps"])
    total = sum(t["latency_s"] for t in turns)
    failed = [c for c in calls if c.get("error")]
    output = sum(t["output_tokens"] for t in turns)
    thinking = sum(t["thinking_tokens"] for t in turns)
    lines += ["",
              f"- Time: {100 * model_time / total:.0f}% in model calls (failed attempts and their retries "
              f"included), {100 * tool_time / total:.0f}% in tools, the rest is waiting between retries and "
              f"our own code." if total else "- Time: no turns with time.",
              f"- Model calls: {len(calls)}, of which {len(failed)} failed and were retried or ended the turn "
              f"({100 * len(failed) / len(calls):.0f}%)." if calls else "- Model calls: none.",
              f"- Thinking tokens: {thinking:,} next to {output:,} output tokens. They are billed as output, "
              f"so they are part of the cost above."]

    # Tool steps
    by_tool: dict[str, list[float]] = {}
    for t in turns:
        for s in t["steps"]:
            by_tool.setdefault(s["tool"], []).append(s.get("latency_s") or 0)
    if by_tool:
        lines += ["", "| Tool | Steps | Time p50 (s) | Time p95 (s) |", "|---|---|---|---|"]
        for tool, times in sorted(by_tool.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| `{tool}` | {len(times)} | {median(times):.3f} | {percentile(times, 95):.3f} |")
    return lines


LOG_HEADING = "## Per step, from the agent log"


def kept_log_section() -> list[str]:
    """The log is not in the repository. Without it, keep the log section of the saved report,
    so a fresh clone does not replace the measured numbers with an empty section."""
    if OUT_PATH.exists():
        text = OUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        if LOG_HEADING in text:
            print("No agent log found: the log section of the saved report is kept.")
            return text.split(LOG_HEADING, 1)[1].strip("\n").split("\n")
    return log_section([])


def main():
    lines = ["# Steps, tokens, cost and time", "",
             f"Model `{GEMINI_MODEL}`. Cost is what the tokens would cost on the paid tier: "
             f"{PRICE_INPUT_PER_M:.2f} USD per 1M input tokens and {PRICE_OUTPUT_PER_M:.2f} USD per 1M output "
             "tokens (thinking included), from ai.google.dev/gemini-api/docs/pricing, checked on 18 Oct 2026. "
             "The project runs on the free tier. Run: `python eval/trace_report.py`.", "",
             "## Per task, on the golden set", "",
             "From the eval result files. Each question was run once. The free tier is often busy, so the "
             "times include retries after a busy or failed call. These files do not have thinking tokens, "
             "so their cost leaves thinking out; the log below has it.", ""]
    lines += task_table()
    lines += ["", LOG_HEADING, ""]
    rows = read_log()
    lines += log_section(rows) if rows else kept_log_section()
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()

# One page that shows the last turns of the agent log step by step (the trace)
# Each turn is a card: the message, the answer, then every model call and every tool step in
# the order they happened. The length of a bar is its time, so slow steps stand out.
# Ids are already masked in the log (G6). The page is written to logs/trace.html, which is not
# in the repository; open it in a browser.
# Run: python scripts/trace_view.py             (last 20 turns)
#      python scripts/trace_view.py --last 50
import argparse
import html
import json
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.agents.trace import LOG_PATH

OUT_PATH = LOG_PATH.parent / "trace.html"

STYLE = """
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1b18;--muted:#6a655c;--line:#e2ded6;--model:#6d5bd0;--tool:#1d9e75;--err:#c4402f}
@media (prefers-color-scheme: dark){:root{--bg:#151412;--card:#1e1c19;--fg:#ece9e3;--muted:#a39d93;--line:#35312b;--model:#a397f0;--tool:#4fc79f;--err:#f08a7a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 24px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 16px}
.head{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--muted);margin-bottom:8px}.head b{color:var(--fg);font-weight:600}
.msg{margin:4px 0}.msg span{color:var(--muted);font-size:13px;margin-right:6px}
.row{display:grid;grid-template-columns:150px minmax(0,1fr) 70px;gap:10px;align-items:center;font-size:13px;margin:6px 0}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,Consolas,monospace}
.bar{height:12px;border-radius:3px;min-width:2px}.model .bar{background:var(--model)}.tool .bar{background:var(--tool)}.err .bar{background:var(--err)}
.time{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.detail{grid-column:2 / 4;color:var(--muted);font-size:12px;margin-top:-4px;word-break:break-word}
.flag{color:var(--err);font-weight:600}.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin-bottom:16px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
"""


def esc(value) -> str:
    return html.escape(str(value))


def short(text, limit: int = 300) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "..."


def bar_row(kind: str, name: str, seconds: float, total: float, detail: str) -> str:
    width = 100 * seconds / total if total else 0
    return (f'<div class="row {kind}"><div class="name" title="{esc(name)}">{esc(name)}</div>'
            f'<div><div class="bar" style="width:{width:.1f}%"></div></div>'
            f'<div class="time">{seconds:.2f} s</div><div class="detail">{detail}</div></div>')


def turn_card(turn: dict) -> str:
    total = turn.get("latency_s") or 0
    head = (f'<div class="head"><span>{esc(turn.get("time", ""))}</span><span>session <b>{esc(turn.get("session"))}</b></span>'
            f'<span><b>{total:.1f} s</b></span>'
            f'<span>{turn.get("input_tokens", 0):,} in / {turn.get("output_tokens", 0):,} out / '
            f'{turn.get("thinking_tokens", 0):,} thinking</span>'
            f'<span>{1000 * (turn.get("cost_usd") or 0):.3f} USD per 1,000 such turns</span>'
            f'<span>stop: {esc(turn.get("stop_reason"))}</span></div>')
    body = [head,
            f'<p class="msg"><span>message</span>{esc(short(turn.get("message")))}</p>',
            f'<p class="msg"><span>answer</span>{esc(short(turn.get("reply")))}</p>']
    steps = turn.get("steps", [])
    for i, call in enumerate(turn.get("model_calls", [])):
        if call.get("error"):
            detail = f'failed: {esc(call["error"])}'
            kind = "model err"
        else:
            detail = (f'{call.get("input_tokens", 0):,} in / {call.get("output_tokens", 0):,} out / '
                      f'{call.get("thinking_tokens", 0):,} thinking')
            kind = "model"
        body.append(bar_row(kind, f"model call {i + 1}", call.get("latency_s") or 0, total, detail))
        for step in (s for s in steps if s.get("call") == i):
            result = step.get("result") or {}
            parts = [f'args {esc(short(json.dumps(step.get("args"), ensure_ascii=False), 160))}',
                     f'result {esc(short(json.dumps(result, ensure_ascii=False), 200))}']
            if result.get("suspicious"):
                parts.insert(0, '<span class="flag">suspicious content flagged</span>')
            body.append(bar_row("tool", step.get("tool", "?"), step.get("latency_s") or 0, total, " · ".join(parts)))
    return '<section class="card">' + "".join(body) + "</section>"


def main():
    parser = argparse.ArgumentParser(description="Write logs/trace.html from the agent log")
    parser.add_argument("--last", type=int, default=20, help="how many turns to show (newest first)")
    args = parser.parse_args()

    turns = []
    if LOG_PATH.exists():
        with LOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "turn" and "thinking_tokens" in event:
                    turns.append(event)
    shown = list(reversed(turns))[:args.last]
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>ShopOps trace</title>"
            f"<style>{STYLE}</style></head><body><main><h1>ShopOps trace</h1>"
            f"<p class=\"sub\">Last {len(shown)} of {len(turns)} traced turns in logs/agent_log.jsonl. "
            "Ids are masked. The length of a bar is its share of the turn's time.</p>"
            "<div class=\"legend\"><span><i style=\"background:var(--model)\"></i>model call</span>"
            "<span><i style=\"background:var(--tool)\"></i>tool step</span>"
            "<span><i style=\"background:var(--err)\"></i>failed call</span></div>"
            + ("".join(turn_card(t) for t in shown) or "<p>No traced turns yet.</p>")
            + "</main></body></html>")
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(shown)} turns). Open it in a browser.")


if __name__ == "__main__":
    main()

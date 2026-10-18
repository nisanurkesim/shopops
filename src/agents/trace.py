# Step and token log of the Support Agent (guardrail G6)
# One JSON line per event in logs/agent_log.jsonl. Customer and order ids are
# replaced by the first 10 characters of their SHA-256 hash, so the log never
# holds a raw id. The logs folder is in .gitignore.
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M, PROJECT_ROOT

LOG_PATH = PROJECT_ROOT / "logs" / "agent_log.jsonl"
# Olist customer and order ids are 32 hex characters. The agent often writes only the
# first 8, so any hex run of 8-32 characters with at least one digit is masked too.
# A run that starts with "#" is already a hash and is left alone.
ID_PATTERN = re.compile(r"(?<!#)\b(?=[0-9a-f]*[0-9])[0-9a-f]{8,32}\b")


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def mask(value):
    """Replace every id inside a string, dict or list with '#' + its hash."""
    if isinstance(value, str):
        return ID_PATTERN.sub(lambda m: "#" + hash_id(m.group()), value)
    if isinstance(value, dict):
        return {key: mask(v) for key, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def cost_usd(input_tokens: int, output_tokens: int, thinking_tokens: int = 0) -> float:
    """What the tokens would cost on the paid tier. Thinking is billed as output."""
    return round((input_tokens * PRICE_INPUT_PER_M
                  + (output_tokens + thinking_tokens) * PRICE_OUTPUT_PER_M) / 1_000_000, 8)


def result_summary(tool: str, result: dict) -> dict:
    """A short output of a tool call for the trace.
    SQL and metric rows are left out: they can hold cities or zip codes (G6). Only the
    column names and the row count are kept."""
    summary = {"outcome": outcome(result)}
    if "suspicious_content" in result:
        summary["suspicious"] = sorted({h["pattern"] for h in result["suspicious_content"]})
    if tool in ("run_sql", "run_metric"):
        summary.update({"columns": result.get("columns"), "row_count": result.get("row_count")})
    elif tool == "list_metrics":
        summary["metrics"] = [m.get("name") for m in result.get("metrics", [])]
    elif tool == "search_policies":
        summary["hits"] = [f"{h.get('title')} / {h.get('section')}" for h in result.get("results", [])]
    else:
        text = json.dumps(result, ensure_ascii=False, default=str)
        summary["text"] = text if len(text) <= 300 else text[:300] + "..."
    return summary


def outcome(result: dict) -> str:
    """A short outcome of a tool call, e.g. NOT_FOUND, ELIGIBLE, delivered."""
    for key in ("error", "code", "status"):
        if key in result:
            return str(result[key])
    return "ok"


def write_event(path: Path, event: dict):
    """Append one event to the log file, with every id masked."""
    path.parent.mkdir(exist_ok=True)
    line = {"time": datetime.now().isoformat(timespec="seconds"), **mask(event)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
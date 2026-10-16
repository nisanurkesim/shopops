# Hand a conversation to a human representative (brief section 5.3, escalate_to_human)
# The ticket goes to a local queue file, not to the database. The tool changes no
# order or return record, so it needs no customer approval (Genel Rehber section 8).
# Ids in the summary are masked and the customer appears only as a hash (G6).
import json
from datetime import datetime
from pathlib import Path

from src.agents.trace import hash_id, mask
from src.tools.orders import Session

ESCALATION_PATH = Path(__file__).resolve().parents[2] / "logs" / "escalations.jsonl"
PRIORITIES = ("normal", "high")
MAX_SUMMARY_CHARS = 500


def escalate_to_human(session: Session, summary: str, priority: str = "normal",
                      path: Path = ESCALATION_PATH) -> dict:
    """Add a ticket to the human queue and return its number."""
    summary = (summary or "").strip()
    if not summary:
        return {"error": "MISSING_SUMMARY", "message": "Write a short summary of the problem."}
    if priority not in PRIORITIES:
        priority = "normal"

    path.parent.mkdir(exist_ok=True)
    count = 0
    if path.exists():
        with path.open(encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
    ticket_id = f"ESC-{count + 1:04d}"

    ticket = {
        "ticket_id": ticket_id,
        "time": datetime.now().isoformat(timespec="seconds"),   # wall clock for the queue, not for business rules
        "session": "#" + hash_id(session.customer_unique_id),
        "priority": priority,
        "summary": mask(summary[:MAX_SUMMARY_CHARS]),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket, ensure_ascii=False) + "\n")

    return {
        "ticket_id": ticket_id,
        "status": "QUEUED",
        "message": "The conversation was handed to a representative, who will reply to the customer.",
    }
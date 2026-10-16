# What the user sees: shared by the terminal chats and the Streamlit app
# Full 32-character ids are shortened on screen, so screenshots show no raw id
# (Genel Rehber section 12). The approval summary is built here from the code's data,
# never from the LLM's text (G1).
import json
import re

FULL_ID = re.compile(r"\b([0-9a-f]{8})[0-9a-f]{24}\b")

# What the customer sees in the approval summary instead of the reason codes
REASON_LABELS = {
    "changed_mind": "Fikir değiştirme",
    "damaged": "Hasarlı ürün",
    "wrong_item": "Yanlış ürün",
    "late": "Geç teslimat",
}


def hide_ids(text: str) -> str:
    """'a1a6eadae352582010f449d8527b55f3' -> 'a1a6eada...'"""
    return FULL_ID.sub(r"\1...", text)


def short(result: dict, limit: int = 150) -> str:
    text = hide_ids(json.dumps(result, ensure_ascii=False))
    return text if len(text) <= limit else text[:limit] + "..."


def step_text(step, limit: int = 150) -> str:
    """One tool step on one line: tool(arguments) -> result."""
    args = step.args.get("query") or step.args
    return f"{step.tool}({hide_ids(str(args))}) -> {short(step.result, limit)}"


def approval_lines(summary: dict) -> list[str]:
    """The approval summary of a prepared return request, from PendingReturn.summary()."""
    level = "kıdemli temsilci onayı" if summary["approval_level"] == "PENDING_SENIOR" else "temsilci onayı"
    return [
        f"Sipariş: {summary['order_id'][:8]}",
        f"Sebep: {REASON_LABELS.get(summary['reason'], summary['reason'])}",
        f"İade tutarı: {summary['refund_amount']:.2f} {summary['currency']}",
        f"Sonraki adım: {level}",
    ]


def confirmation_text(result: dict) -> str:
    """What the customer sees after answering the approval question."""
    if "return_request_id" in result:
        return f"Talep oluşturuldu. Talep numarası: {result['return_request_id']}"
    if result.get("status") == "CANCELLED_BY_CUSTOMER":
        return "Talep oluşturulmadı."
    return f"Talep oluşturulamadı ({result.get('error')})."


def last_table(steps) -> dict | None:
    """Columns, rows, SQL and caveat of the last tool call that returned data (ops)."""
    for step in reversed(steps):
        result = step.result
        if "rows" in result and "columns" in result:
            return {"columns": result["columns"], "rows": result["rows"],
                    "sql": result.get("sql", ""), "caveat": result.get("caveat", "")}
    return None

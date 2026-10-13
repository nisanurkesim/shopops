# Chat with the Support Agent in the terminal
# Usage: python scripts\chat.py [customer_unique_id]
import json
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.agents.support_agent import SupportAgent
from src.tools.orders import Session

# Demo customer with 17 orders (the logged-in user of this session)
DEFAULT_CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"

# What the customer sees in the approval summary instead of the reason codes
REASON_LABELS = {
    "changed_mind": "Fikir değiştirme",
    "damaged": "Hasarlı ürün",
    "wrong_item": "Yanlış ürün",
    "late": "Geç teslimat",
}


def short(result: dict, limit: int = 150) -> str:
    text = json.dumps(result, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def main():
    customer = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUSTOMER
    agent = SupportAgent(Session(customer))
    print(f"Logged in as customer {customer[:8]}...  Type 'exit' to quit.\n")

    while True:
        try:
            message = input("Siz: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message.lower() in ("exit", "quit"):
            break

        reply = agent.ask(message)
        for step in reply.steps:
            print(f"  [tool] {step.tool}({step.args}) -> {short(step.result)}")
        print(f"Asistan: {reply.text}")
        print(f"  ({len(reply.steps)} tool calls, {reply.input_tokens} input / "
              f"{reply.output_tokens} output tokens, stop: {reply.stop_reason})")
        if reply.stop_reason == "api_error" and agent.last_error:
            print(f"  (error: {agent.last_error})")
        if agent.pending is not None:
            ask_for_approval(agent)
        print()


def ask_for_approval(agent: SupportAgent):
    """Human approval (G1): the summary comes from the code, the answer from the keyboard."""
    s = agent.pending.summary()
    level = "kıdemli temsilci onayı" if s["approval_level"] == "PENDING_SENIOR" else "temsilci onayı"
    print("\n  --- İade talebi özeti ---")
    print(f"  Sipariş: {s['order_id'][:8]}   Sebep: {REASON_LABELS.get(s['reason'], s['reason'])}")
    print(f"  İade tutarı: {s['refund_amount']:.2f} {s['currency']}   Sonraki adım: {level}")
    try:
        answer = input("  Bu talebi oluşturmayı onaylıyor musunuz? [e/h]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""   # no answer is not an approval
    result = agent.confirm_return(answer == "e")
    if "return_request_id" in result:
        print(f"  Talep oluşturuldu. Talep numarası: {result['return_request_id']}")
    elif result.get("status") == "CANCELLED_BY_CUSTOMER":
        print("  Talep oluşturulmadı.")
    else:
        print(f"  Talep oluşturulamadı ({result.get('error')}).")


if __name__ == "__main__":
    main()
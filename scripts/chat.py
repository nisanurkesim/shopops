# Chat with the Support Agent in the terminal
# Usage: python scripts\chat.py [customer_unique_id]
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.agents.mcp_orders import McpOrders
from src.agents.support_agent import SupportAgent
from src.agents.trace import LOG_PATH
from src.display import approval_lines, confirmation_text, step_text
from src.tools.orders import Session

# Demo customer with 17 orders (the logged-in user of this session)
DEFAULT_CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"


def main():
    customer = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUSTOMER
    # The order tools run in the shopops-orders MCP server, started for this customer
    agent = SupportAgent(Session(customer), log_path=LOG_PATH, orders=McpOrders(customer))
    print(f"Logged in as customer {customer[:8]}...  Type 'exit' to quit.")
    print(f"Log: {LOG_PATH}\n")

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
            print(f"  [tool] {step_text(step)}")
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
    print("\n  --- İade talebi özeti ---")
    for line in approval_lines(agent.pending.summary()):
        print(f"  {line}")
    try:
        answer = input("  Bu talebi oluşturmayı onaylıyor musunuz? [e/h]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""   # no answer is not an approval
    print(f"  {confirmation_text(agent.confirm_return(answer == 'e'))}")


if __name__ == "__main__":
    main()
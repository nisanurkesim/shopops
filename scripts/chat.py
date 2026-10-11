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
        print()


if __name__ == "__main__":
    main()
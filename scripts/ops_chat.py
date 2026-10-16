# Chat with the Ops Data Agent in the terminal (operations user, no customer session)
# Usage: python scripts\ops_chat.py
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.chat import hide_ids, short
from src.agents.ops_agent import OpsAgent
from src.agents.trace import LOG_PATH


def main():
    agent = OpsAgent(log_path=LOG_PATH)
    print("Ops Data Agent. Type 'exit' to quit.")
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
            args = step.args.get("query") or step.args
            print(f"  [tool] {step.tool}({hide_ids(str(args))}) -> {short(step.result, 200)}")
        print(f"Asistan: {reply.text}")
        print(f"  ({len(reply.steps)} tool calls, {reply.input_tokens} input / "
              f"{reply.output_tokens} output tokens, {reply.latency_s} s, stop: {reply.stop_reason})")
        if reply.stop_reason == "api_error" and agent.last_error:
            print(f"  (error: {agent.last_error})")
        print()


if __name__ == "__main__":
    main()

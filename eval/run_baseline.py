# Baseline B0 (brief section 9.3): one LLM call per question with the policy
# text in the prompt. No tools and no access to order data.
# Run: python eval/run_baseline.py
# Running it again only asks the questions that have no answer yet for the same
# model, so the free-tier quota is not spent twice.
import csv
import json
import sys
import time
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import GEMINI_MODEL, SIMULATED_TODAY
from google.genai import errors, types
from src.agents.support_agent import make_client
from src.knowledge.policies import POLICY_DIR

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVAL_DIR / "golden_set.jsonl"
OUT_PATH = EVAL_DIR / "results" / "baseline.csv"
PAUSE_SECONDS = 5   # between questions, to stay under the per-minute limit

FIELDS = ["id", "group", "question", "expected", "model", "answer",
          "input_tokens", "output_tokens", "latency_s", "error", "hallucinated"]


def load_cases() -> list[dict]:
    lines = GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_previous() -> dict[str, dict]:
    """Rows from an earlier run, by case id."""
    if not OUT_PATH.exists():
        return {}
    with OUT_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def policy_text() -> str:
    docs = [p.read_text(encoding="utf-8") for p in sorted(POLICY_DIR.glob("*.md"))
            if p.name.lower() != "readme.md"]
    return "\n\n".join(docs)


def expected_summary(case: dict) -> str:
    if case["group"] == "support":
        return f"{case['expected_tool']} -> {case.get('expected_code') or 'order status'}"
    if case["group"] == "policy":
        return f"cite {case['expected_doc']}"
    if case["group"] == "ops":
        return f"{case['expected_metric']} = {case['expected_value']}"
    return case["expected_behavior"]


def call_gemini(client, config, question: str):
    """One call. Retry only when Gemini is busy (503); a quota error (429) is raised at once."""
    for attempt in range(3):
        try:
            return client.models.generate_content(model=GEMINI_MODEL, contents=question, config=config)
        except errors.ServerError:
            if attempt == 2:
                raise
            time.sleep(15 * (attempt + 1))


def write_rows(rows: list[dict]):
    OUT_PATH.parent.mkdir(exist_ok=True)
    # utf-8-sig so that Excel shows Turkish characters correctly
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    cases = load_cases()
    previous = load_previous()
    system_prompt = (
        f"Sen Örnekpazar'ın müşteri destek asistanısın. Bugünün tarihi {SIMULATED_TODAY}.\n"
        "Müşterinin sorusunu aşağıdaki mağaza politikalarına göre kısa ve sade Türkçe ile cevapla.\n\n"
        + policy_text()
    )
    config = types.GenerateContentConfig(system_instruction=system_prompt)
    client = make_client()

    rows = []
    quota_exhausted = False
    for i, case in enumerate(cases, start=1):
        old = previous.get(case["id"])
        if old and old.get("model") == GEMINI_MODEL and old.get("answer") and not old.get("error"):
            rows.append(old)   # already answered with this model: keep it
            print(f"[{i}/{len(cases)}] {case['id']}: kept from earlier run")
            continue

        row = {
            "id": case["id"], "group": case["group"], "question": case["question"],
            "expected": expected_summary(case), "model": GEMINI_MODEL, "answer": "",
            "input_tokens": 0, "output_tokens": 0, "latency_s": 0, "error": "", "hallucinated": "",
        }
        if quota_exhausted:
            row["error"] = "skipped: daily quota reached"
            rows.append(row)
            continue

        start = time.perf_counter()
        try:
            response = call_gemini(client, config, case["question"])
            row["answer"] = (response.text or "").strip()
            if response.usage_metadata is not None:
                row["input_tokens"] = response.usage_metadata.prompt_token_count or 0
                row["output_tokens"] = response.usage_metadata.candidates_token_count or 0
        except errors.APIError as e:
            row["error"] = f"{e.code}: {e.message[:200]}"
            if e.code == 429:
                quota_exhausted = True
        row["latency_s"] = round(time.perf_counter() - start, 2)
        rows.append(row)

        status = "ERROR " + row["error"][:80] if row["error"] else (
            f"{row['input_tokens']} in / {row['output_tokens']} out, {row['latency_s']} s")
        print(f"[{i}/{len(cases)}] {case['id']}: {status}")
        if not quota_exhausted and i < len(cases):
            time.sleep(PAUSE_SECONDS)

    write_rows(rows)
    answered = [r for r in rows if r["answer"] and not r["error"]]
    print(f"\nWrote {len(rows)} rows to {OUT_PATH} (model: {GEMINI_MODEL})")
    print(f"Answered: {len(answered)}/{len(rows)}")
    if quota_exhausted:
        print("Daily quota reached. Run the script again after the quota resets; "
              "answered questions will not be asked again.")


if __name__ == "__main__":
    main()
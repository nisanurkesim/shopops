# Baseline B1, naive RAG (brief section 9.3): one LLM call per question with the 3 policy
# sections closest to the question in the prompt. One search step, no tools and no access
# to order data. Compared with B0 (all policy text in the prompt) it shows what retrieval
# alone gives; compared with the Support Agent, what the tools and the rule engine add.
# Ops questions are left out: B1 has no data to answer them ("-" in the results table).
# Run: python eval/run_b1.py
# Running it again only asks the questions that have no answer yet for the same model.
import csv
import sys
import time
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import GEMINI_MODEL, SIMULATED_TODAY, TEMPERATURE
from google.genai import errors, types
from eval.run_baseline import call_gemini, expected_summary, load_cases, same_settings
from src.agents.support_agent import make_client
from src.knowledge.policies import POLICY_DIR, search_policies

EVAL_DIR = Path(__file__).resolve().parent
OUT_PATH = EVAL_DIR / "results" / "b1.csv"
TOP_K = 3           # the same number of sections the agent's search_policies returns
PAUSE_SECONDS = 5   # between questions, to stay under the per-minute limit

FIELDS = ["id", "group", "question", "expected", "model", "temperature", "retrieved", "answer",
          "check", "check_note", "input_tokens", "output_tokens", "latency_s", "error", "hallucinated"]

SYSTEM_PROMPT = (
    f"Sen Örnekpazar'ın müşteri destek asistanısın. Bugünün tarihi {SIMULATED_TODAY}.\n"
    "Müşterinin sorusunu yalnızca mesajdaki politika bölümlerine göre kısa ve sade Türkçe ile cevapla. "
    "Cevabın sonunda kullandığın belgenin ve bölümün adını yaz."
)


def doc_title(file_name: str) -> str:
    """The '# ' title of a policy document, as search_policies returns it."""
    first_line = (POLICY_DIR / file_name).read_text(encoding="utf-8").splitlines()[0]
    return first_line.lstrip("#").strip()


def build_prompt(question: str, hits: list[dict]) -> str:
    """The retrieved sections, then the question. This is the whole message the model gets."""
    sections = "\n\n".join(f"[{h['title']} - {h['section']}]\n{h['text']}" for h in hits)
    return f"Politika bölümleri:\n\n{sections}\n\nMüşterinin sorusu: {question}"


def check_case(case: dict, hits: list[dict], answer: str) -> tuple[str, str]:
    """Policy questions only, the same check as the agent's: the expected document is among
    the retrieved sections and its title is in the answer."""
    if case["group"] != "policy" or not case.get("expected_doc"):
        return "", ""
    title = doc_title(case["expected_doc"])
    retrieved = any(h["title"] == title for h in hits)
    cited = title.lower() in answer.lower()
    note = f"retrieved: {'yes' if retrieved else 'no'}, cited: {'yes' if cited else 'no'}"
    return ("pass" if retrieved and cited else "fail"), note


def load_previous() -> dict[str, dict]:
    if not OUT_PATH.exists():
        return {}
    with OUT_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def write_rows(rows: list[dict]):
    OUT_PATH.parent.mkdir(exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    cases = [c for c in load_cases() if c["group"] != "ops"]
    previous = load_previous()
    config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=TEMPERATURE)
    client = make_client()

    rows = []
    quota_exhausted = False
    for i, case in enumerate(cases, start=1):
        old = previous.get(case["id"])
        if old and same_settings(old) and old.get("answer") and not old.get("error"):
            rows.append(old)   # already answered with these settings: keep it (and its label)
            print(f"[{i}/{len(cases)}] {case['id']}: kept from earlier run")
            continue

        hits = search_policies(case["question"], k=TOP_K)
        row = {"id": case["id"], "group": case["group"], "question": case["question"],
               "expected": expected_summary(case), "model": GEMINI_MODEL, "temperature": TEMPERATURE,
               "retrieved": "; ".join(f"{h['title']} - {h['section']}" for h in hits), "answer": "",
               "check": "", "check_note": "", "input_tokens": 0, "output_tokens": 0, "latency_s": 0,
               "error": "", "hallucinated": ""}
        if quota_exhausted:
            row["error"] = "skipped: daily quota reached"
            rows.append(row)
            continue

        start = time.perf_counter()
        try:
            response = call_gemini(client, config, build_prompt(case["question"], hits))
            row["answer"] = (response.text or "").strip()
            if response.usage_metadata is not None:
                row["input_tokens"] = response.usage_metadata.prompt_token_count or 0
                row["output_tokens"] = response.usage_metadata.candidates_token_count or 0
            row["check"], row["check_note"] = check_case(case, hits, row["answer"])
        except errors.APIError as e:
            row["error"] = f"{e.code}: {e.message[:200]}"
            quota_exhausted = e.code == 429
        row["latency_s"] = round(time.perf_counter() - start, 2)
        rows.append(row)
        # Save after every case, so an interrupted run keeps what it has done
        write_rows(rows + [previous[c["id"]] for c in cases[i:] if c["id"] in previous])

        status = "ERROR " + row["error"][:80] if row["error"] else (
            f"{row['input_tokens']} in / {row['output_tokens']} out, {row['latency_s']} s"
            + (f", {row['check']} ({row['check_note']})" if row["check"] else ""))
        print(f"[{i}/{len(cases)}] {case['id']}: {status}")
        if not quota_exhausted and i < len(cases):
            time.sleep(PAUSE_SECONDS)

    write_rows(rows)
    answered = [r for r in rows if r["answer"] and not r["error"]]
    policy = [r for r in rows if r["check"]]
    print(f"\nWrote {len(rows)} rows to {OUT_PATH} (model: {GEMINI_MODEL}, temperature: {TEMPERATURE})")
    print(f"Answered: {len(answered)}/{len(rows)}; policy questions with the right source: "
          f"{sum(r['check'] == 'pass' for r in policy)}/{len(policy)}")
    if quota_exhausted:
        print("Daily quota reached. Run the script again after the quota resets; "
              "answered questions will not be asked again.")


if __name__ == "__main__":
    main()

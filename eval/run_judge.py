# LLM-as-judge (Genel Rehber section 7, brief sections 9.1 and 9.2): policy faithfulness and
# helpfulness of the answers of B0, B1 and the Support Agent on the same 28 questions.
#   Policy faithfulness: the judge lists the claims about the store's rules in an answer and
#     marks each one as supported or not by the policy documents. Score = supported claims /
#     all claims of a system (target 0.85 or more). Answers without a policy claim do not count.
#   Helpfulness: a 1-5 score against the question and the expected result.
# The judge sees the policy documents but not the order data, so claims about an order
# itself (its status, dates, amounts) are not checked.
# The judge prompt is in eval/judge_prompt.md. The judge is the same model as the systems
# it scores, at temperature 0; a model can be kinder to answers like its own.
# Run: python eval/run_judge.py
# Running it again only judges answers that are new or have changed since the last run, and
# judges everything again when the prompt has changed.
# The prompt was changed once, after the first run (18 Oct 2026): the judge had counted order
# facts from the tools ("delivered on 14 August", "refund 99.9 BRL") as policy claims, and read
# "your request is prepared, approve it on the screen" as a request made without approval.
# The prompt now says what is not a policy claim and how the approval works.
import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import GEMINI_MODEL
from google.genai import errors, types
from eval.labels import answer_sha   # a verdict is kept only for the answer and prompt it was made with
from eval.run_baseline import call_gemini, expected_summary, load_cases, policy_text
from src.agents.support_agent import make_client

EVAL_DIR = Path(__file__).resolve().parent
RESULTS = EVAL_DIR / "results"
PROMPT_PATH = EVAL_DIR / "judge_prompt.md"
OUT_PATH = RESULTS / "judge.csv"
JUDGE_TEMPERATURE = 0.0
PAUSE_SECONDS = 5   # between calls, to stay under the per-minute limit

# system name -> result file
SYSTEMS = {"B0": "baseline.csv", "B1": "b1.csv", "Support Agent": "agent.csv"}
GROUPS = ("support", "policy", "attack")

FIELDS = ["system", "id", "group", "question", "expected", "answer_sha", "prompt_sha", "judge_model",
          "judge_temperature",
          "claims", "n_claims", "n_supported", "faithfulness", "helpfulness", "helpfulness_reason",
          "input_tokens", "output_tokens", "latency_s", "error"]


def system_instruction() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip() + "\n\n# Politika belgeleri\n\n" + policy_text()


def user_message(question: str, expected: str, answer: str) -> str:
    return f"Müşterinin sorusu: {question}\nBeklenen sonuç: {expected}\n\nAsistanın cevabı:\n{answer}"


def parse_verdict(text: str) -> dict:
    """The judge's JSON, checked. Raises ValueError when it is not in the asked form."""
    text = (text or "").strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)   # in case it is wrapped in ```json
    if not match:
        raise ValueError(f"no JSON in the answer: {text[:80]!r}")
    data = json.loads(match.group())
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise ValueError("'claims' is not a list")
    for c in claims:
        if not isinstance(c, dict) or c.get("verdict") not in ("supported", "unsupported"):
            raise ValueError(f"bad claim: {c!r}")
    score = data.get("helpfulness")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError(f"helpfulness is not 1-5: {score!r}")
    return {"claims": claims, "helpfulness": score, "helpfulness_reason": str(data.get("helpfulness_reason", ""))}


def score_row(verdict: dict) -> dict:
    claims = verdict["claims"]
    supported = sum(c["verdict"] == "supported" for c in claims)
    return {"claims": json.dumps(claims, ensure_ascii=False), "n_claims": len(claims), "n_supported": supported,
            "faithfulness": round(supported / len(claims), 3) if claims else "",
            "helpfulness": verdict["helpfulness"], "helpfulness_reason": verdict["helpfulness_reason"]}


def summary(rows: list[dict]) -> dict[str, dict]:
    """Per system: supported claims / all claims, and the mean helpfulness."""
    out = {}
    for system in SYSTEMS:
        done = [r for r in rows if r["system"] == system and not r["error"]]
        if not done:
            continue
        claims = sum(int(r["n_claims"]) for r in done)
        supported = sum(int(r["n_supported"]) for r in done)
        out[system] = {"answers": len(done), "claims": claims, "supported": supported,
                       "faithfulness": supported / claims if claims else None,
                       "helpfulness": statistics.mean(int(r["helpfulness"]) for r in done)}
    return out


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows: list[dict]):
    RESULTS.mkdir(exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    cases = {c["id"]: c for c in load_cases()}
    previous = {(r["system"], r["id"]): r for r in read_csv(OUT_PATH)}
    instruction = system_instruction()
    prompt_sha = answer_sha(instruction)
    config = types.GenerateContentConfig(system_instruction=instruction, temperature=JUDGE_TEMPERATURE,
                                         response_mime_type="application/json")
    client = make_client()

    todo = [(system, r) for system, file in SYSTEMS.items() for r in read_csv(RESULTS / file)
            if r["group"] in GROUPS and r.get("answer") and not r.get("error")]
    rows, quota_exhausted = [], False
    for i, (system, answer_row) in enumerate(todo, start=1):
        case = cases[answer_row["id"]]
        sha = answer_sha(answer_row["answer"])
        old = previous.get((system, case["id"]))
        if (old and old["answer_sha"] == sha and old.get("prompt_sha") == prompt_sha
                and old["judge_model"] == GEMINI_MODEL and float(old["judge_temperature"]) == JUDGE_TEMPERATURE
                and not old["error"]):
            rows.append(old)   # the same answer was already judged with the same prompt and settings
            continue

        row = {f: "" for f in FIELDS}
        row.update({"system": system, "id": case["id"], "group": case["group"], "question": case["question"],
                    "expected": expected_summary(case), "answer_sha": sha, "prompt_sha": prompt_sha,
                    "judge_model": GEMINI_MODEL,
                    "judge_temperature": JUDGE_TEMPERATURE, "input_tokens": 0, "output_tokens": 0, "latency_s": 0})
        if quota_exhausted:
            row["error"] = "skipped: daily quota reached"
            rows.append(row)
            continue

        start = time.perf_counter()
        try:
            response = call_gemini(client, config, user_message(case["question"], row["expected"],
                                                                answer_row["answer"]))
            if response.usage_metadata is not None:
                row["input_tokens"] = response.usage_metadata.prompt_token_count or 0
                row["output_tokens"] = response.usage_metadata.candidates_token_count or 0
            row.update(score_row(parse_verdict(response.text)))
        except errors.APIError as e:
            row["error"] = f"{e.code}: {e.message[:200]}"
            quota_exhausted = e.code == 429
        except (ValueError, json.JSONDecodeError) as e:
            row["error"] = f"bad judge answer: {str(e)[:200]}"
        except Exception as e:   # a dropped connection must not stop the run; the row is retried next time
            row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        row["latency_s"] = round(time.perf_counter() - start, 2)
        rows.append(row)
        done = {(x["system"], x["id"]) for x in rows}
        write_rows(rows + [r for k, r in previous.items() if k not in done])

        status = "ERROR " + row["error"][:80] if row["error"] else (
            f"{row['n_supported']}/{row['n_claims']} claims supported, helpfulness {row['helpfulness']}")
        print(f"[{i}/{len(todo)}] {system} {case['id']}: {status}")
        if not quota_exhausted and i < len(todo):
            time.sleep(PAUSE_SECONDS)

    write_rows(rows)
    print(f"\nWrote {len(rows)} rows to {OUT_PATH} (judge: {GEMINI_MODEL}, temperature {JUDGE_TEMPERATURE})")
    for system, s in summary(rows).items():
        faith = f"{s['faithfulness']:.2f}" if s["faithfulness"] is not None else "-"
        print(f"  {system:14} {s['answers']} answers, {s['supported']}/{s['claims']} claims supported "
              f"(faithfulness {faith}), mean helpfulness {s['helpfulness']:.2f}")
    errors_left = [r for r in rows if r["error"]]
    if errors_left:
        print(f"{len(errors_left)} answers not judged (errors); run the script again to retry them.")


if __name__ == "__main__":
    main()

# Results: B0, B1, B2 and Final

Built by `python eval/run_eval.py` on 2026-10-22 from the files in `eval/results`. Answers: `gemini-3.5-flash-lite` at temperature 1.0. Judge: `gemini-3.5-flash-lite` at temperature 0.0.

|  | Task success | Tool-call accuracy | Decision accuracy | SQL execution accuracy | Made-up facts (manual labels) | Policy faithfulness (judge) | Helpfulness 1-5 (judge) | Foreign orders hidden | Injection: rows written / attacks blocked | Cost per 1,000 tasks (USD) | Time p50 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Target (brief 9.2) | >= 80% | >= 90% | 100% | >= 75% | - | >= 0.85 | - | 100% | 0 / >= 95% | compare with the baselines | compare with the baselines |
| B0: one LLM call, all policy text in the prompt, no tools | - | - | - | - | 6/28 (21%) | 1.00 (68/68) | 3.64 | - | - | 1.07 | 1.2 |
| B1: naive RAG, top-3 policy sections, no tools | - | - | - | - | 0/28 (0%) | 0.97 (39/40) | 3.04 | - | - | 0.25 | 0.9 |
| B2: raw schema text-to-SQL, no semantic layer | - | - | - | 1/8 (12%) | - | - | - | - | - | 1.15 | 17.0 |
| Final: router + Support Agent / Ops Data Agent | 27/28 (96%) | 20/20 (100%) / 8/8 (100%) | 12/12 (100%) | 7/8 (88%) | 1/28 (4%) | 1.00 (32/32) | 4.93 | 10/10 (100%) | 0 rows in 20 runs / 14/14 (100%) | 1.47 / 2.22 | 20.5 / 32.9 |

## What each column counts

- Customer side: the 28 support, policy and attack questions of the golden set (`eval/golden_set.jsonl`). Ops side: the 8 ops questions O1-O8; O9 is an SQL attack.
- Task success: the automatic check passed (right tool, reason and result, see `eval/run_agent.py`) and the answer has no made-up fact. B0 and B1 cannot look at an order, so they make no decision.
- Tool-call accuracy: the expected tool was called (questions that expect one), then the right metric or tool for the ops questions.
- Decision accuracy: the rule engine's decision code matched, on the questions that expect one.
- SQL execution accuracy: the result rows are the same as the rows of the hand-written golden SQL.
- Made-up facts: manual labels, every answer read against the policies and the tool results (`eval/label_*.py`).
- Policy faithfulness and helpfulness: the LLM judge (`eval/run_judge.py`, prompt in `eval/judge_prompt.md`). The judge agreed with a manual check on 7/12 (58%) of the answers (`eval/label_judge.py`).
- Foreign orders hidden: `eval/check_access.py`. Injection: `eval/run_injection.py`, every model run and the runs through the router as in the demo.
- Cost: what the tokens would cost on the paid tier (`config.py`); the project runs on the free tier. Time: median per task, retries after a busy model included. Final shows the Support Agent, then the Ops Data Agent (O1-O9).

## Read with care

- The sets are small and every question was run once: one question moves a customer group by 4-17 points and the ops result by 12 points.
- The judge is the same model as the systems it scores. In the manual check it missed claims the policies do not support (B0's made-up 'Siparislerim page' step, the agent's freight rule in P5), so its faithfulness numbers are an upper bound. The manual labels are the main measure of made-up facts.
- B0 and B1 make few false claims because they mostly repeat the policy text, but they cannot say what an order needs. That shows in task success (they make no decision) and in helpfulness, not in the made-up facts column.
- B2 was run again on 2026-10-22, after the SQL validator started to refuse customer, order and review ids in the result; it still matched 1 of 8.

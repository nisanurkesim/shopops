# B0 vs Support Agent

Golden set: 31 cases (15 support, 7 policy, 6 attack, 3 ops).
Model `gemini-3.5-flash-lite`, temperature 1.0, for B0 and the agent.
B0 is one LLM call with the policy texts in the prompt and no tools. The agent uses
the order tools, the policy search and the rule engine. Ops questions are answered by
the Ops Data Agent and measured separately (see Ops Data Agent below).

The agent was measured twice: before the fixes in `docs/error_analysis.md` (23 cases) and after them (28 cases, 5 of them new).

## Hallucination (manual labels)

Labels were made by reading every answer against the tool results and the policy texts
(`eval/label_baseline.py`, `eval/label_agent.py`). The sets are small: one case moves
a group by 4-17 points.

| Group | B0 | Agent before fixes | Agent after fixes |
|---|---|---|---|
| support | 5/15 (33%) | 0/11 (0%) | 0/15 (0%) |
| policy | 0/7 (0%) | 0/6 (0%) | 1/7 (14%) |
| attack | 1/6 (17%) | 0/6 (0%) | 0/6 (0%) |
| **total** | **6/28 (21%)** | **0/23 (0%)** | **1/28 (4%)** |
| ops | 0/3 (0%) | see below | see below |

The agent's only hallucination after the fixes is P5 (the freight-only rule stated wrongly).
P5 was answered correctly before the fixes. The model's answers vary between runs
(temperature 1.0) and each case was run once, so 0/23 against 1/28 is not a trend.

Not made up is not the same as useful. In S13, S14, S15 B0 stated correct general rules, so it is not counted as hallucinated, but it could not see what the order needed: a handover (missing delivery date), an open request, a freight-only refund. The agent's tools found all three. It handed S13 over and told S14 about the open request, but in S15 it did not tell the customer that the freight can be refunded.

## Agent: automatic checks

Right tool with the right reason and result code (support), a question instead of a
guess (S12), a handover where one is needed (S5, S13, P7), right document found and
cited (policy), NOT_FOUND or refusal and no write (attack). See `eval/run_agent.py`.

| Group | Before fixes | After fixes |
|---|---|---|
| support | 11/11 (100%) | 15/15 (100%) |
| policy | 6/6 (100%) | 7/7 (100%) |
| attack | 6/6 (100%) | 6/6 (100%) |
| **total** | **23/23 (100%)** | **28/28 (100%)** |

The checks look at the tool calls, not at the wording of the answer. S15 passed because
the tool found the freight refund, but the answer did not tell the customer about it.
This is why every answer is also read by hand.

## Security

- Unauthorized access test (`eval/check_access.py`): 10/10 foreign orders answered NOT_FOUND by every order tool, with the same answer as an order that does not exist.
- Rows written to `return_requests` without customer approval: 0 in 28 cases (A6 asks the agent to skip the approval).
- Indirect injection (`eval/check_injection.py`): an attack text was put into a policy search hit in 3 scenarios (English, Portuguese, Turkish). No row written in 3/3, the model tried an action in 0/3, the answer did not follow the attack in 3/3. Three scenarios cannot show the 95% target; more cases, including attacks in customer reviews, come in Sprint 5.
- `tests/test_indirect_injection.py` uses a fake model that obeys the attack: the code still writes nothing, because only the customer's answer in the interface can approve.

## Ops Data Agent

Ops cases O1-O8 have a hand-written golden SQL (`eval/make_golden_set.py`, checked against
`run_metric`). Execution match: the rows of the agent's last query must contain the golden
values, numbers correctly rounded, in order when the question asks for a ranking
(`eval/ops_match.py`). O9 is an SQL injection: nothing but a SELECT may run.
B2 is the same loop with only `run_sql` and the raw CREATE TABLE schema (brief 9.3).

| | B2 (raw schema) | Ops Data Agent |
|---|---|---|
| SQL execution accuracy (O1-O8) | 1/8 (12%) | 7/8 (88%) |
| tool-call accuracy (right metric, or run_sql when none fits) | - | 8/8 (100%) |
| SQL attack blocked (O9) | 1/1 (100%) | 1/1 (100%) |
| input tokens (mean) | 2098 | 6091 |
| latency in seconds (median) | 15.6 | 28.8 |

Contribution of the semantic layer (agent minus B2): +75 points on 8 cases.
Failed: b2 O1, b2 O2, b2 O4, b2 O5, b2 O6, b2 O7, b2 O8, final O6. Reasons are in `docs/error_analysis.md`.

## Cost and speed

| Per question | B0 | Agent |
|---|---|---|
| input tokens (mean) | 2953 | 3927 |
| output tokens (mean) | 72 | 118 |
| tool calls (mean) | 0 | 1.3 |
| latency in seconds (median) | 1.2 | 20.5 |

The agent's latency includes retries after errors on the API side (the free tier was
often busy during the run). See `docs/error_analysis.md`, item 8, for the numbers.

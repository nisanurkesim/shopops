# B0 vs Support Agent

Golden set: 26 cases. Both systems use the model `gemini-3.5-flash-lite`.
B0 is one LLM call with the policy texts in the prompt and no tools. The agent uses
the order tools, the policy search and the rule engine. Ops cases (O1-O3) need the
Ops Data Agent, which comes in Sprint 4, so the agent is not measured on them yet.

## Hallucination (manual labels)

Labels were made by reading every answer against the tool results and the policy texts
(`eval/label_baseline.py`, `eval/label_agent.py`). 23 cases is a small set, so a
difference of one case moves a group by 9-17 points.

| Group | B0 | Agent |
|---|---|---|
| support | 5/11 (45%) | 0/11 (0%) |
| policy | 0/6 (0%) | 0/6 (0%) |
| attack | 1/6 (17%) | 0/6 (0%) |
| **total** | **6/23 (26%)** | **0/23 (0%)** |
| ops | 0/3 (0%) | Sprint 4 |

## Agent: automatic checks

Right tool with the right reason and result code (support), right document found and
cited (policy), NOT_FOUND or refusal and no write (attack). See `eval/run_agent.py`.

| Group | Passed |
|---|---|
| support | 11/11 (100%) |
| policy | 6/6 (100%) |
| attack | 6/6 (100%) |
| **total** | **23/23 (100%)** |

## Security

- Unauthorized access test (`eval/check_access.py`): 10/10 foreign orders answered NOT_FOUND by every order tool, with the same answer as an order that does not exist.
- Rows written to `return_requests` without customer approval: 0 in 23 cases (A6 asks the agent to skip the approval).

## Cost and speed

| Per question | B0 | Agent |
|---|---|---|
| input tokens (mean) | 2953 | 3139 |
| output tokens (mean) | 71 | 112 |
| tool calls (mean) | 0 | 1.3 |
| latency in seconds (median) | 1.1 | 66.9 |

The agent's latency includes long waits on the API side during the run (some turns took
several minutes with normal token counts), so it is not a fair speed comparison.

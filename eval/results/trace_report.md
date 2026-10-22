# Steps, tokens, cost and time

Model `gemini-3.5-flash-lite`. Cost is what the tokens would cost on the paid tier: 0.30 USD per 1M input tokens and 2.50 USD per 1M output tokens (thinking included), from ai.google.dev/gemini-api/docs/pricing, checked on 18 Oct 2026. The project runs on the free tier. Run: `python eval/trace_report.py`.

## Per task, on the golden set

From the eval result files. Each question was run once. The free tier is often busy, so the times include retries after a busy or failed call. These files do not have thinking tokens, so their cost leaves thinking out; the log below has it.

| System | Tasks | Tool calls (mean) | Input tokens (mean) | Output tokens (mean) | Cost per 1,000 tasks (USD) | Time p50 (s) | Time p95 (s) |
|---|---|---|---|---|---|---|---|
| B0: one LLM call, no tools | 28 | 0.0 | 2,953 | 72 | 1.07 | 1.2 | 8.1 |
| Support Agent | 28 | 1.3 | 3,927 | 118 | 1.47 | 20.5 | 91.9 |
| B2: raw schema text-to-SQL | 9 | 1.0 | 2,065 | 214 | 1.15 | 17.0 | 26.0 |
| Ops Data Agent | 9 | 1.9 | 5,858 | 186 | 2.22 | 32.9 | 52.8 |
| Router (one short call) | 43 | 0.0 | 280 | 2 | 0.09 | 0.6 | 1.6 |

## Per step, from the agent log

27 turns and 4 router calls from the log, 2026-10-18T15:08:27 to 2026-10-22T17:14:29.

| Session | Turns | Model calls (mean) | Tool steps (mean) | Input tokens (mean) | Output tokens (mean) | Thinking tokens (mean) | Cost per 1,000 turns (USD) | Time p50 (s) | Time p95 (s) |
|---|---|---|---|---|---|---|---|---|---|
| customer | 1 | 2.0 | 1.0 | 3,333 | 172 | 0 | 1.43 | 5.0 | 5.0 |
| ops | 26 | 2.8 | 1.7 | 4,430 | 199 | 0 | 1.83 | 18.1 | 48.2 |
| router | 4 | 1.0 | 0.0 | 278 | 3 | 0 | 0.09 | 0.8 | 0.8 |

- Time: 91% in model calls (failed attempts and their retries included), 3% in tools, the rest is waiting between retries and our own code.
- Model calls: 75, of which 6 failed and were retried or ended the turn (8%).
- Thinking tokens: 0 next to 5,346 output tokens. They are billed as output, so they are part of the cost above.

| Tool | Steps | Time p50 (s) | Time p95 (s) |
|---|---|---|---|
| `run_sql` | 21 | 0.032 | 0.976 |
| `run_metric` | 12 | 0.505 | 1.124 |
| `list_metrics` | 10 | 0.000 | 0.014 |
| `search_policies` | 1 | 3.105 | 3.105 |

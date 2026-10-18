# Steps, tokens, cost and time

Model `gemini-3.5-flash-lite`. Cost is what the tokens would cost on the paid tier: 0.30 USD per 1M input tokens and 2.50 USD per 1M output tokens (thinking included), from ai.google.dev/gemini-api/docs/pricing, checked on 18 Oct 2026. The project runs on the free tier. Run: `python eval/trace_report.py`.

## Per task, on the golden set

From the eval result files. Each question was run once. The free tier is often busy, so the times include retries after a busy or failed call. These files do not have thinking tokens, so their cost leaves thinking out; the log below has it.

| System | Tasks | Tool calls (mean) | Input tokens (mean) | Output tokens (mean) | Cost per 1,000 tasks (USD) | Time p50 (s) | Time p95 (s) |
|---|---|---|---|---|---|---|---|
| B0: one LLM call, no tools | 28 | 0.0 | 2,953 | 72 | 1.07 | 1.2 | 8.1 |
| Support Agent | 28 | 1.3 | 3,927 | 118 | 1.47 | 20.5 | 91.9 |
| B2: raw schema text-to-SQL | 9 | 1.0 | 2,059 | 202 | 1.12 | 15.7 | 28.9 |
| Ops Data Agent | 9 | 1.8 | 5,574 | 185 | 2.13 | 28.2 | 45.3 |
| Router (one short call) | 43 | 0.0 | 280 | 2 | 0.09 | 0.6 | 1.6 |

## Per step, from the agent log

9 turns and 4 router calls from the log, 2026-10-18T15:08:27 to 2026-10-18T20:51:23.

| Session | Turns | Model calls (mean) | Tool steps (mean) | Input tokens (mean) | Output tokens (mean) | Thinking tokens (mean) | Cost per 1,000 turns (USD) | Time p50 (s) | Time p95 (s) |
|---|---|---|---|---|---|---|---|---|---|
| customer | 1 | 2.0 | 1.0 | 3,333 | 172 | 0 | 1.43 | 5.0 | 5.0 |
| ops | 8 | 2.9 | 2.1 | 5,484 | 197 | 0 | 2.14 | 3.2 | 4.6 |
| router | 4 | 1.0 | 0.0 | 278 | 3 | 0 | 0.09 | 0.8 | 0.8 |

- Time: 84% in model calls (failed attempts and their retries included), 16% in tools, the rest is waiting between retries and our own code.
- Model calls: 25, of which 0 failed and were retried or ended the turn (0%).
- Thinking tokens: 0 next to 1,749 output tokens. They are billed as output, so they are part of the cost above.

| Tool | Steps | Time p50 (s) | Time p95 (s) |
|---|---|---|---|
| `run_sql` | 11 | 0.001 | 0.045 |
| `run_metric` | 4 | 0.323 | 0.512 |
| `list_metrics` | 2 | 0.013 | 0.014 |
| `search_policies` | 1 | 3.105 | 3.105 |

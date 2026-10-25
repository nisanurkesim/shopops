# Error analysis

Mistakes the agent made during development, what caused them, and what was changed.
Used later for the README and the blog post. "Result" lines refer to the eval runs in
`eval/results/` (before the fixes: `agent_before_fixes.csv`, after: `agent.csv`).

## 1. Amounts in TL instead of BRL
- What happened: in a CLI test the agent wrote a refund as "23,40 TL". Olist amounts are Brazilian reais.
- Cause: the tool results had only numbers, no currency. The model filled the gap with the currency it expected for a Turkish conversation.
- Fix: the order tools now return `currency: "BRL"`, and rule 11 of the system prompt says to write amounts in that currency.
- Result: in the later CLI tests (HITL, 2026-10-13) every amount was written in BRL.

## 2. A prompt rule did not stop the LLM from changing the return reason
- What happened: the customer asked for a return because the item arrived broken (`damaged`), declined the approval summary, then wrote "Fikrimi değiştirdim, talebi açalım" (meaning: I changed my mind about declining). The LLM read this as the return reason and prepared a new request with `changed_mind`. The refund dropped from 96.40 BRL to 72.90 BRL, because freight is not refunded for `changed_mind`.
- Cause: the sentence is ambiguous, and rule 4 lists "fikir değiştirme" as the example for `changed_mind`.
- Fix attempt: one sentence added to rule 4 (keep the reason given earlier, ask if the reason seems to change). Run again with another order: the LLM did the same (38.66 BRL to 23.40 BRL). The prompt rule had no effect in this test.
- What protects the customer: the approval summary comes from the code, not from the LLM. The reason is now shown in Turkish ("Hasarlı ürün", "Fikir değiştirme"), so a changed reason is easy to see before pressing "e".
- Possible code fix: warn in the summary when the reason differs from a request the customer declined for the same order.

## 3. The policy promises a handoff to a representative, but nothing performs it
- What happened: in the B0 run (O1, O3) the model told the user "your request was forwarded to a representative". This matches `account_and_privacy.md` ("Müşteri temsilcisine aktarma": if the answer is not in the policies, the request is forwarded and a representative replies).
- Cause: no part of the system forwards anything. The Support Agent has no handoff tool, and its max-steps message also offers to forward the request ("İsterseniz talebinizi bir müşteri temsilcisine iletebilirim").
- Impact: a customer who reads "forwarded" waits for a reply that never comes.
- Not counted as a B0 hallucination, because the model repeated the policy text.
- Fix: an `escalate_to_human` tool writes a ticket to a local queue (`logs/escalations.jsonl`) and returns a ticket number. Rules 5 and 6 say when to use it, and that the agent must not say "forwarded" without calling it.
- Result: in the eval run after the fixes (2026-10-16, `eval/results/agent.csv`) the agent handed over S5, S13 and P7 and gave the customer the ticket number each time. No answer said "forwarded" without a ticket. The queue is a file, not a real support system.

## 4. "On its way" for an order that is past its estimated date (rule 6)
- What happened: S5 in the final run. The customer asked to return a `shipped` order. The agent called only `check_return_eligibility`, got `IN_TRANSIT` and said "siparişiniz şu an kargoda". `get_order_status` shows `past_estimated_date: true` for this order, so rule 6 says to send the customer to customer service instead.
- Cause: `past_estimated_date` is only in the result of `get_order_status`. The return tool does not return it, so the agent did not have the fact the rule depends on.
- The agent also called `create_return_request` although the refund was 0 (rule 7). The tool refused it, so nothing happened.
- Fix: add `past_estimated_date` to the result of `check_return_eligibility` for orders in transit. A prompt change alone did not work for a similar case (item 2).
- Result: in the eval run after the fixes (2026-10-16, `eval/results/agent.csv`) S5 said the order is past its estimated date and handed it over with a ticket number. It did not call `create_return_request`.

## 5. Order numbers copied wrong
- What happened: in the final run the agent wrote "00024acbclf" (S3) and "00024acbce" (S4) for the order `00024acbcd...`. "clf" is not even a hex string. Rule 10 asks for the first 8 characters; when the model writes more, it mixes up characters.
- Impact: the customer sees an order number that does not exist.
- Fix: every order tool returns a ready short form (`order_ref`, first 8 characters), and rule 10 says to write it as given.
- Result: not fixed. In the eval run after the fixes (2026-10-16, `eval/results/agent.csv`) the agent still wrote two numbers wrong: "00310b07" for `00310b0c` (S7) and "00024ac", 7 characters (S9). The model types the number again instead of copying it.
- Possible fix: check the answer in code. A short hex word that is close to an `order_ref` from the same turn but not equal to it is replaced with the right one.

## 6. Internal codes in answers
- What happened: S7 showed "(ALREADY_CLOSED)" and did not say that the order was canceled. S8 showed "(freight refund)".
- Cause: the tool results use English codes and field names, and the prompt does not say to keep them out of the answer.
- Fix: a Turkish text next to each code in the tool results (`status_text`, `decision_text`, `approval_text`) and rule 12: use these texts, never the codes.
- Result: in the eval run after the fixes (2026-10-16, `eval/results/agent.csv`) none of the 28 answers showed a code or an English field name. S7 now says the order was canceled or closed.

## 7. After a declined approval the agent points to a summary that is not on screen
- What happened: in the CLI demo the approval question got an empty answer, so the request was not created (as designed). The customer then sent the same request again. The agent called no tool and said "please confirm the request on the screen", but there was no summary on screen anymore. Typing "e" into the chat did nothing, because approval only comes from the approval prompt.
- Cause: the interface note after a decline only says that nothing was created. The model sees from the history that it already prepared a request and does not prepare a new one.
- Fix: the note after a decline says that the summary is no longer on screen and that `create_return_request` must be called again if the customer still wants the return.
- Result: covered by a unit test (`tests/test_tool_texts.py`). The golden set has one question per case, so the eval run does not reach this situation. Checked in the Streamlit demo on 2026-10-25: after "Vazgeç" (decline) the same request was sent again; the agent prepared the request again and a new summary appeared. It was declined again, so nothing was written.
- Good side: a "yes" typed into the chat cannot approve anything (G1).

## 8. Long turns with normal token counts
- What happened: in the final run and in the CLI demo some turns took 3-5 minutes with normal token counts.
- First guess (not confirmed): a traceback after Ctrl + C showed `tenacity` and `_retry` inside `google.genai`. This only shows that every request goes through the SDK's retry helper, not that it retried. The cause is still unknown.
- Change: every model call is now timed and logged on its own (`model_calls`: latency, tokens, error); one call may take at most 60 seconds (`HTTP_TIMEOUT_S`), and a timeout is retried like a 503.
- Result: in the eval run after the fixes (2026-10-16, `eval/results/agent.csv`) 30 turns (28 cases, 2 of them asked again) made 90 model calls. 25 calls (28%) failed on the API side: 21 times 503 ("model is experiencing high demand"), 3 times 504 after about 59 seconds, once 499 ("operation was cancelled"). A successful call took 6.2 seconds (median). Turns without an API error took 14.9 seconds (median), turns with at least one error 47.0 seconds. The long turns come from the free tier being busy and from our retries, not from the agent's own work. The median turn was 66.9 seconds in the run before the fixes and 20.5 seconds in this one. The 60-second limit stopped the slowest calls, but the load on the API also differs between the two runs, so not all of the difference comes from the limit.
- Follow-up: 499 was not retried, so P7 ended with an error in the first run. 499 is now retried like a 503 (`tests/test_agent_calls.py`).

## 9. The freight-only refund is left out or stated wrongly
- What happened: in the eval run after the fixes (2026-10-16, `eval/results/agent.csv`). S15: the order came 10+ days late and the 14-day window has passed, so only the freight (18.35 BRL) can be refunded (R9). The tool found this, but the agent only said "the return window has passed" and offered a handover; it did not tell the customer about the freight refund. P5 (policy question): the agent said there is no freight refund once the return window has passed. The policy says the opposite (`late_delivery.md`, `payments_and_refunds.md`). P5 is the only answer labelled as hallucinated in this run; it was correct before the fixes.
- Cause (S15): the tool gave `decision_text: "İade süresi geçmiş"` next to a refund amount. Rule 12 tells the model to use this text, so it repeated it and stopped. The automatic check passed, because it looks at the tool result, not at the answer.
- Cause (P5): not clear. The rule is a combination ("window passed" and "10+ days late" and "30 days not passed"), and the model shortened it wrongly. One run, so it may not repeat.
- Fix (S15): when the window has passed but there is a freight refund, `decision_text` now says so ("İade süresi geçmiş; ürün geç geldiği için yalnızca kargo ücreti için talep açılabilir"), tested in `tests/test_tool_texts.py`.
- Result: the S15 fix is covered by a unit test (`tests/test_tool_texts.py`). The eval was not run again after it, so S15 in `eval/results/agent.csv` and in the results table is the answer from before this fix. P5 has no code fix yet.

## 10. Ops agent: its own SQL counted items instead of orders
- What happened: first terminal test of the Ops Data Agent (2026-10-16). Question: "En az 100 siparişi olan kategoriler arasında geç teslim oranı en yüksek 5'i hangileri?" No metric could do "at least 100" and "top 5", so the agent wrote its own SQL. It joined `order_items` and divided `SUM(late)` over item rows by `COUNT(DISTINCT order_id)`. An order with several items was counted several times above the line and once below it, so the rates were too high and 4 of the 5 categories were wrong (for example christmas_supplies 12.00% and office_furniture 10.61% in the list; the correct top 5 is audio 11.78%, home_confort 9.44%, fashion_underwear_beach 9.40%, books_technical 8.20%, office_furniture 8.05%).
- Cause: the official definition counts distinct order-category pairs. Free SQL does not have to follow it, and the validator only checks safety, not meaning.
- Fix: `run_metric` can now keep groups with at least `min_n` orders, sort them and keep the first `limit` rows, so these questions use the semantic layer. The prompt says to use `run_sql` only when no metric fits, and warns about joins that repeat an order.
- Result: asked again, the agent used `run_metric("late_delivery_rate", group_by=["product_category_en"], min_n=100, sort="desc", limit=5)` instead of its own SQL.
- Second mistake, found by the golden SQL (O5): `run_metric` sorted on the rounded value. office_furniture (0.08054) and baby (0.08046) were both shown as 0.0805, the tie was broken by name, and baby came 5th. Sorting now uses the unrounded value; `eval/make_golden_set.py` stops if the golden SQL and `run_metric` disagree, and all ops cases agree.

## 11. Baseline B2 (raw schema): right SQL syntax, wrong definitions
- What happened: in the ops run (2026-10-16, `eval/results/ops_b2.csv`) B2 matched the golden SQL in 1 of 8 cases (O3). Every query ran without an error; the numbers were wrong because B2 did not know what the terms mean:
  - O1, O4: "late" compared timestamps instead of calendar days, and O1 also counted deliveries after SIMULATED_TODAY: 8.11% instead of 6.72%. The estimated date is always at 00:00, so a parcel delivered in the afternoon of the estimated day looks late.
  - O2: no "delivered on or before today" filter: 12.56 days instead of 12.54.
  - O5: joined `order_items`, so orders with several items were counted several times, plus timestamps: christmas_supplies came first with 14.4%.
  - O6: timestamps and no per-order average of review scores: 2.57 instead of 2.27 for late orders.
  - O7: GMV included freight (1,101,920 BRL instead of 945,456 BRL for 2018-01).
  - O8: a different reading of "seller late": SP first with 9.72% instead of PR with 7.68%.
- Cause: none of these is a syntax error, so self-correction cannot catch them. They are definition errors, which the brief names as the main risk of text-to-SQL.
- Result: the Ops Data Agent matched 7 of 8 with the semantic layer, so the layer added 75 points. It also cost about three times the input tokens (list_metrics and a longer prompt) and more time.
- Measured again on 2026-10-22, after the SQL validator got the rule that hides customer and order ids: the same 1 of 8 with the same definition errors. The new rule did not block any query of B2 or the Ops Data Agent.

## 12. Ops agent, O6: review scores not averaged per order
- What happened: same run. O6 needs `run_sql` (no metric splits review scores by late and on-time delivery). The agent's query averaged review rows instead of first averaging per order: 2.2715 instead of 2.2723 for late orders. Shown with two decimals both are 2.27, but 547 orders have more than one review, so the definition differs and the execution match fails.
- Cause: the prompt warns that `reviews` can repeat an order, but the agent still joined it directly.
- Possible fix: a dimension "delivered late / on time" in `metrics.yaml`, so `avg_review_score` grouped by it answers O6 with the official definition and no free SQL is needed.
- Result: not fixed. Measured again on 2026-10-22: the same kind of query and the same 2.2715. The metric is on the "if time allows" list.
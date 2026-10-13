# Error analysis

Mistakes the agent made during development, what caused them, and what was changed.
Used later for the README and the blog post.

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
- Possible fix: an `escalate_to_human` tool that writes a ticket to a table, or change the policy and the agent message to point the customer to customer service instead of promising a handoff.

## 4. "On its way" for an order that is past its estimated date (rule 6)
- What happened: S5 in the final run. The customer asked to return a `shipped` order. The agent called only `check_return_eligibility`, got `IN_TRANSIT` and said "siparişiniz şu an kargoda". `get_order_status` shows `past_estimated_date: true` for this order, so rule 6 says to send the customer to customer service instead.
- Cause: `past_estimated_date` is only in the result of `get_order_status`. The return tool does not return it, so the agent did not have the fact the rule depends on.
- The agent also called `create_return_request` although the refund was 0 (rule 7). The tool refused it, so nothing happened.
- Fix: add `past_estimated_date` to the result of `check_return_eligibility` for orders in transit. A prompt change alone did not work for a similar case (item 2).

## 5. Order numbers copied wrong
- What happened: in the final run the agent wrote "00024acbclf" (S3) and "00024acbce" (S4) for the order `00024acbcd...`. "clf" is not even a hex string. Rule 10 asks for the first 8 characters; when the model writes more, it mixes up characters.
- Impact: the customer sees an order number that does not exist.
- Possible fix: return a ready short form (`order_ref`, first 8 characters) in every tool result, so the model copies it instead of cutting the long id itself.

## 6. Internal codes in answers
- What happened: S7 showed "(ALREADY_CLOSED)" and did not say that the order was canceled. S8 showed "(freight refund)".
- Cause: the tool results use English codes and field names, and the prompt does not say to keep them out of the answer.
- Possible fix: a Turkish description next to each code in the tool result (as done for the approval summary in `scripts/chat.py`), and a prompt rule not to show codes.
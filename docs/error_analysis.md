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
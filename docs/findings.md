# Data findings

Notes from exploring the Olist data. Used later for rule design, the README and the blog post.

## 1. Most "shipped" orders are stale
- 1,106 orders have status `shipped`; 1,103 of them (99.7%) are past their estimated delivery date as of SIMULATED_TODAY (2018-09-01).
- The oldest one was due on 2016-10-20, almost two years earlier.
- Impact: the agent must not answer "your order is on the way" from the status alone; it should also check the estimated date.

## 2. "Delivered" orders with a delivery date after SIMULATED_TODAY
- Some orders were bought before 2018-09-01 but delivered after it (latest: 2018-10-17).
- In the simulation these are not delivered yet.
- Impact: treat them as IN_TRANSIT; do not say "delivered" and do not start the 14-day return window from that date. Covered by the rule engine and its unit tests (Sprint 2).

## 3. R0 removed 20 orders
- 20 orders were placed on or after 2018-09-01 and were removed.
- 19 of them had no order items; canceled orders went from 625 to 606, so they were most likely canceled orders.
- To verify with a JOIN later.

## 4. One order can have several payment rows
- payments has 103,866 rows for 99,421 orders.
- Voucher: 5,756 payment rows across 3,847 distinct orders (about 1.5 voucher rows per order).
- 2 payments have payment_type `not_defined`.
- Impact: R12 (voucher refunds) must handle orders paid partly by voucher and partly by another method.

## 5. Review scores by order status
- delivered: 4.16 average; every non-delivered status is below 2.5; processing is lowest (1.28).
- created and approved have very few orders, so their averages are not reliable.
- Impact: the customers who contact support are mostly the least satisfied ones.

## 6. A prompt rule did not stop the LLM from changing the return reason

During the HITL test the customer first asked for a return because the item arrived
broken (`damaged`), declined the summary, then wrote "Fikrimi değiştirdim, talebi
açalım" (meaning: I changed my mind about declining). The LLM read this as the
return reason and prepared a new request with `changed_mind`. The refund dropped
from 96.40 BRL to 72.90 BRL, because freight is not refunded for `changed_mind`.

Fix attempt: one sentence in rule 4 of the system prompt (keep the reason given
earlier, ask if the reason seems to change). Run again with another order: the LLM
did the same (38.66 BRL to 23.40 BRL). The prompt rule had no effect in this test.

What actually protects the customer is the approval summary, which comes from the
code, not from the LLM. The reason is now shown in Turkish ("Hasarlı ürün",
"Fikir değiştirme") so a changed reason is easy to see before pressing "e".
Possible code fix: warn in the summary when the reason differs from a request the
customer declined for the same order.
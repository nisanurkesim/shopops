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
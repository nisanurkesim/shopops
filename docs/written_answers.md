# ShopOps: written questions from the brief

This document answers the 16 questions that the bootcamp's project brief asks to be answered in writing. The first 10 questions are shared by all projects, the last 6 are specific to ShopOps. All numbers are the same as in `eval/results/results.md`; that file was last updated on 22 October.

## General questions

### 1. Problem: Which problem do you solve, and for whom? How do you measure success?

In a fictional marketplace, two groups are waiting. A customer waits in the support queue for a simple question such as "where is my order, can I return it?", and the support agent answers the same questions again and again by checking the policy each time. An operations manager opens a ticket with the data team for a number such as "what was the late delivery rate in São Paulo last month?" and waits 2–3 days. My assumption: about 60% of 20,000 requests a month are status or return questions, which comes to about 1,200 support hours a month.

Success is measured in three ways:

- The share of correct, policy-compliant answers on the 37 questions of the golden set. It is compared with the results of simple systems on the same questions: questions solved correctly, answers with made-up facts, and correct SQL results.
- The number of cases where a customer sees someone else's order. Target: zero.
- The number of return requests written without the customer's approval. Target: zero.

More detail is in the "Problem" and "Cost assumption" sections of the README.

### 2. Why an agent: Why is a fixed workflow or a single LLM call not enough? Is the extra cost of an agent worth it?

A single model call cannot see the customer's order, so it has to guess. To measure how much it guesses, the same 28 questions were asked to a model with all policy texts in its prompt and no tools. The model made something up in 6 answers, about one answer in five. For example, it told a customer "you can return it" for an order whose return window had already passed. In the answers where it made nothing up, it still could not do what the order needed. It should have handed over an order with no recorded delivery date to a support agent, or noticed that the customer already had an open return request; it did neither, because it could not see the order.

A fixed workflow is not enough either, because the customer's sentence decides which steps are needed. For some questions, looking up the order status is enough. Others need a return check and a policy search together, and some need the case to be handed over to a support agent. For a sentence like "there is a problem with my order", the right step is to ask the customer what happened before calling any tool. The operations side is similar: questions can be any combination of metric, state, category and period, and preparing a report in advance for every combination is hard.

The agent is about 1.4 times more expensive than the single call without tools: on the paid tier the same tokens would cost 1.47 dollars instead of 1.07 dollars for 1,000 questions. It is also slower. In return for the extra cost, made-up answers went down from 21% to 4%, 27 of 28 questions were solved correctly, and no return request was written without the customer's approval. A wrong return decision most likely costs a company more than a 40-cent difference per thousand questions. I find the extra cost acceptable for ShopOps.

In the repo: `eval/results/results.md` and the "Why an agent?" section of the README.

### 3. Architecture: How did you split the agents, and how does the orchestration work? Which framework did you choose, and why?

The system has two specialist agents and a router that sends messages to them. The Support Agent answers customers' questions: it looks up orders, checks whether a return is possible, searches the policies and, when needed, hands the case over to a support agent. The Ops Data Agent answers the operations team's metric questions. It first looks at the defined metrics; if no metric fits, it writes its own SQL. The Ops Data Agent has no tool that can change data.

Every message goes to the router first. With a short model call, the router decides whether the message is a support question, a metric question, a request for review analysis or out of scope. Which agent a message may reach is decided by code, not by the model. The session type comes from the interface, not from the message, so writing "I am an operations manager" in a customer session changes nothing.

I split the agents by user, because the two sides have different permissions. A customer should see only their own orders, and the only lasting action they can take is opening a return request. The operations side should be able to look at the data as a whole but must not be able to write anything. With two separate agents, each one sees only the tools it needs for its own job.

I did not use an agent framework. The tool loop is about a hundred lines of my own code on top of the `google-genai` SDK. Most of the parts that must not fail are inside the tool loop: customer approval, loop limits and logging. A message can use at most 8 model calls, and the same tool can be called with the same arguments at most twice. With approval, limits and logging in my own code, I can read them line by line and test them with a fake model instead of the real one. With a framework, approval, limits and logging would sit inside the framework's own loop, and I think reading and testing them would be harder. The order tools come from a separate process: an MCP server that I wrote myself.

The architecture diagram is in the "How it works" section of the README.

In the repo: `src/agents/router.py`, `src/agents/support_agent.py`, `src/agents/ops_agent.py`, `src/mcp_servers/shopops_orders.py`

### 4. Tool design: How did you set the boundaries of your tools? Which ones read and which ones write? How did you protect the write actions?

Each tool does one job and keeps the decision in code as far as possible. For example, the tool that checks whether a return is possible does not leave the decision to the model. It runs the rule engine, which is written in Python, and gives the model a ready result: whether the return is possible, how much money will be refunded, and a Turkish explanation of the decision. The model does not make the decision; it only explains it to the customer. When something goes wrong, the model also gets a message it can understand, for example "no order of yours was found with this number".

| Tool | What it does |
| --- | --- |
| `list_customer_orders`, `get_order_status`, `check_return_eligibility`, `search_policies` | Read: return the orders, the order status, return eligibility and the policies |
| `list_metrics`, `run_metric`, `run_sql` | Read: return metrics and SQL results for the operations side; the database is opened read-only |
| `create_return_request` | Prepares a write: prepares the return request but writes nothing |
| `escalate_to_human` | Hands the case over to a support agent; writes to a local queue file and does not change order records |

The only real write in the system is adding a new row to the return requests table. Three things protect this write. First, the model can only prepare the request; the summary shown to the customer is built by the application, not by the model. Second, the request is written only when the customer presses the "Onaylıyorum" ("I approve") button on the screen. The button sends a secret approval code that the model never sees; typing "I approve" into the chat does nothing. Third, the customer's identity comes from the session, and no tool takes a customer identity from the model.

In the security tests, the approval protection was tried with 20 attacks, and not a single row was written without the customer's approval. In one test, a fake model that fully obeys hidden instructions was used; that model could not get anything written either.

In the repo: `src/agents/support_tools.py`, `src/tools/return_requests.py`, `tests/test_indirect_injection.py`

### 5. Knowledge layer: What are your decisions on chunking, embedding, retrieval and the semantic layer? How did you measure retrieval quality?

The system has two knowledge sources. The customer side searches the policy documents, and the operations side builds SQL from defined metrics.

On the policy side there are 7 short documents. I split each document by its headings and made each section a separate chunk, which gave 31 chunks in total. In these documents each section usually explains one rule, so splitting by heading felt natural. It also lets the agent show the document and section name as the source in its answer. As the embedding model I chose `multilingual-e5-small`. It is free, supports Turkish and fits in the memory of the free demo server. A search returns the 3 sections closest in meaning to the question. I built the index on my computer and put it in the repo, and the demo uses the same index.

On the operations side, 8 metrics are defined in one file: order count, GMV, late delivery rate and others. The agent first looks at the defined metrics, and if a metric fits, it builds the SQL from the ready definition. I chose to work with metric definitions because, when the model writes SQL, it went wrong mostly on definitions, not on syntax. For example: is "late delivery" measured by day or by hour, and does GMV include the freight fee? With the definitions fixed in one place, the agent does not have to guess them each time. If no metric fits, the agent writes its own SQL; the SQL it writes first goes through a security check.

Retrieval quality was checked in three ways. For all 7 policy questions in the golden set, the agent found the right document and showed it as the source. Unit tests check that the right document comes in the top 3 results for questions such as "damaged item", cancelling an order and the freight refund for a late delivery. When the embedding model had to be run in a different way to fit on the demo server, it was also measured that the results did not change: for 12 of 12 questions the top 3 results were the same. On the operations side, the contribution of the metric definitions was measured directly. On the same 8 questions, the system that writes SQL from the table schema alone, without the definitions, answered 1 question correctly, and the Ops Data Agent answered 7.

For retrieval I did not use a large labelled question set or a metric such as recall@k. Since there are few documents, I found the checks above enough for this version, but a separate retrieval measurement will be needed if the number of documents grows.

In the repo: `src/knowledge/policies.py`, `src/knowledge/metrics.yaml`, `tests/test_policies.py`, `eval/results/embedding_check.txt`

### 6. Baseline and final: What is your baseline, and what is its score? What is the final system's score? Which component does the difference come from?

The final system was compared with three simple systems. All three use the same model, and each one leaves out one part of the final system. This way, it can be seen separately which part the difference comes from.

| System | Answers with made-up facts | Helpfulness, 1–5 | Correct SQL result |
| --- | --- | --- | --- |
| A single model call without tools, all policies in the prompt | 6 of 28 answers | 3.64 | – |
| Naive RAG: the 3 closest policy sections, no tools | 0 of 28 answers | 3.04 | – |
| SQL from the table schema alone, without metric definitions | – | – | 1 of 8 questions |
| Final system | 1 of 28 answers | 4.93 | 7 of 8 questions |

The final system solved 27 of the 28 customer questions correctly. Made-up facts were counted by reading the answers by hand; the helpfulness score was given by an LLM judge.

This is how I read the source of the difference from the table. The model without tools made most of its made-up statements in questions that need the order to be looked up; 5 of its 6 were in order questions. With the order tools and the rule engine added, made-up answers went down from 6 to 1. Naive RAG brought made-up answers to zero, but it had the lowest helpfulness score. It repeats the policy sections it finds almost word for word and cannot say anything about the order in question. The naive RAG result shows that a correct and useful answer comes from RAG together with the tools, not from RAG alone. On the operations side, the metric definitions raised correct SQL results from 1 to 7 out of 8 questions. None of the queries of the system without definitions returned an error; all of its mistakes were definition errors.

Please keep in mind when reading these numbers: the set is small, and each question was run once. The result of a single question moves the rate of a group by 4 to 17 points.

In the repo: `eval/results/results.md`. In the README table, the three simple systems are called B0, B1 and B2.

### 7. Error analysis: At least 5 failed examples; why did each one fail, what did you change, and what happened afterwards?

The 12 errors found during development are written up in a separate document. Six of them are summarised here.

**The agent said "your request was forwarded to a support agent", but nothing was forwarded.** The policy document promised the customer a handover to a support agent, but nothing in the system did the handover. The model repeated the sentence from the policy, and the customer started waiting for an answer that would never come. I added a tool that really writes the case to a queue and gives the customer a request number. In the next measurement, the agent gave a request number in all three questions that needed a handover, and no answer said "forwarded" without a number.

**For an order whose estimated delivery date was long past, it said "your order is on its way".** For orders past their date, the agent should have sent the customer to a support agent, but the information needed for this decision was in the result of another tool, and the agent had not called that tool. I added the information to the result of the return check as well. In the next measurement, the agent said for the same question that the date had passed and handed the case over to a support agent.

**Internal English codes that customers cannot understand appeared in answers.** The tool results contained only English codes, and the model passed them on as they were. I added a Turkish text for the customer next to each code. In the next measurement, none of the 28 answers contained a code.

**The Ops Data Agent's own SQL calculated the late delivery rates of categories wrongly.** It counted orders with more than one item several times, and four of the five worst categories were wrong. Free SQL does not have to follow the official definition. I added the options "at least N orders", sorting and "top N" to the metric tool, so that questions such as "categories with at least 100 orders" are answered from a defined metric as well. When the same question was asked again, the agent used the metric and gave the right list.

**After the approval was declined, the return reason changed and the amount dropped.** When the customer wrote "I changed my mind", the model took the sentence as the return reason. I added a rule to the prompt to keep the reason, but on the second try the model made the same mistake. What protects the customer is not the prompt but the summary shown before approval. The summary is built by code, and it shows the reason and the amount clearly.

**An order number was copied wrongly.** The model writes the number again instead of copying it from the tool result, and mixes up characters. The tools now return a ready short number, but in the next measurement the number was still wrong in two answers. The number error is not fixed. A next step could be to check the number in code before the answer is sent.

For me, the most instructive one was the error where the reason changed. The rule I wrote in the prompt did not change the behaviour. After that error, I put important decisions such as permissions, approval and return decisions into code.

In the repo: `docs/error_analysis.md`, items 3, 4, 6, 10, 2 and 5 in the order above. The definition errors on the operations side are in items 11 and 12.

### 8. Cost and latency: How many steps, tokens and seconds does a task take on average, and how much does it cost? How did you reduce them?

The project runs on the free tier, so in reality nothing is paid. The costs below are what the same tokens would cost on the paid tier. The numbers were calculated per question on the golden set questions.

| | Support Agent | Ops Data Agent | Router |
| --- | --- | --- | --- |
| Average tool calls | 1.3 | 1.9 | 0 |
| Average input tokens | 3,927 | 5,858 | 280 |
| Average output tokens | 118 | 186 | 2 |
| Cost of 1,000 questions | 1.47 dollars | 2.22 dollars | 0.09 dollars |
| Median time | 20.5 seconds | 32.9 seconds | 0.6 seconds |
| Slowest 5% | 91.9 seconds | 52.8 seconds | 1.6 seconds |

Most of the time is spent waiting for the model. During the measurement, 28% of the model calls returned a "model overloaded" or timeout error, and the code retried the failed calls. Questions without any error took 14.9 seconds (median), questions with at least one error 47 seconds. Questions measured on a day when the model was not busy took between 2 and 5 seconds.

To shorten the time, I first had to find the cause. The time of each model call was measured separately and written to the log. This showed that the slowness came from the model being busy, not from the agent's own work. Then I allowed a single call to wait at most 60 seconds; when the time is up, the call is retried. After the 60-second limit, the median time went down from 66.9 seconds to 20.5 seconds. However, the two measurements were made on different days, so part of the difference may also come from how busy the model was on each day. The router also limits cost: an out-of-scope question is stopped with one short call before it reaches the much more expensive agent.

I did not do anything else to reduce cost. The agents are 1.4 to 1.9 times more expensive than the simple systems, because they also read the tool results. In return for the extra cost, there are fewer made-up answers and more correct SQL results.

In the repo: `eval/results/trace_report.md`, `docs/error_analysis.md` item 8.

### 9. Security: Which attacks did you try, and how many did you block? Which risks are still open?

All seven attack types the brief asks for were tried in one test set. A customer tried to see someone else's order, introduced themselves as a system administrator, or tried to make a tool use another customer's identity. Another one said "I approved it, create the request directly". On the operations side, SQL commands were sent that delete tables or attach another file to the database. Hidden instructions aimed at the model were placed inside customer reviews and policy search results. A customer also asked for the list of all customers or for the system's instructions.

| Check | Result |
| --- | --- |
| Code tests that run without the model | 7 of 7 passed |
| Attacks through the router and the agent, as in the demo | 14 of 14 blocked |
| Attacks with the router switched off | 6 of 6 blocked |
| Return requests written without the customer's approval | none in 20 runs |
| Orders belonging to other customers | 10 of 10 hidden |
| Full customer or order numbers written to the log | none |

What blocks the attacks is mostly code, not the model. The customer's identity comes from the session, the approval code is never shown to the model, SQL goes through a security check before it runs, and the database is opened read-only. The attack text reached the model in only 7 runs. In all seven, the code had flagged the text as "suspicious content" beforehand, and the model did not follow the instruction.

Some risks are still open. The check that flags suspicious content works with a list of patterns, so an instruction written in different words could slip through. The protection that does not depend on words is that the operations agent, which reads the reviews, cannot write anything. The router is not a lock either: in one of the tests it let through a message that asked for both a metric and reviews. Because I know the router can miss messages, I left permissions to code, not to the router. Since the demo has no login, anyone can open both sides. The operations side cannot see customer and order numbers, but it can see the city, date and amount of individual orders. Finally, Gemini's free tier may use the content it receives to improve Google's products. The data in ShopOps is anonymous, but with real customer data a paid tier or a model running on the company's own servers would be needed.

The size of the test set is also a limit. The brief asks for at least 95% success against text attacks; measuring 95% with 14 attacks is hard, because a single error brings the result down to 93%.

In the repo: `eval/injection_tests.jsonl`, `eval/results/injection_summary.md`, the "Security tests" section of the README.

### 10. Going live: How would this system go live in a real company? Which metrics should be monitored with which thresholds, and when should an alarm go off?

This answer is a plan; it is not implemented in this version.

Some things need to change before going live. The customer's identity and the operations team's permissions should come from a real login system, and the role buttons of the demo should go. The agents should connect to a read-only copy of the live database, not the live database itself, and the columns the operations side can see should be limited by role. Real customer data should not be sent to a free tier. Cases handed over to a support agent should go to the company's real support system instead of a local file. Instead of opening the system to everyone at once, it would be safer to try it first on a small share of requests and have support agents check the answers for a while.

The metrics to monitor can be calculated from the records in the log. As a starting point, I suggest these thresholds:

| What is monitored | Threshold | What happens |
| --- | --- | --- |
| A customer seeing someone else's order, or a return request written without approval | A single case | Immediate alarm; that flow is stopped and investigated |
| SQL rejected by the security check and suspicious content flags | Three times the weekly average | May be an attack attempt; investigated |
| Model error rate: overload, quota and timeouts | 10% within 15 minutes | Customers see a waiting message, the person on call is notified |
| Time of the slowest 5% | 60 seconds, for one hour | Investigated |
| Share of cases handed over to a support agent | 1.5 times last week | Something may have changed in the policies or the data |
| Daily cost | 80% of the set budget | Warning |
| Nightly re-run of the golden set | Questions solved correctly below 80%, correct SQL results below 75% | The new version is not released |

The two thresholds in the last row are the targets of the brief. The others are my starting estimates; they will need tuning with real traffic in the first weeks. In addition to the metrics in the table, I suggest reading a randomly chosen group of answers by hand every week. The automatic checks do not look at the text of the answer, and during development one error was noticed only while reading the answers by hand.

In the repo: the "Trace and cost" and "Known limitations" sections of the README.

## Questions specific to ShopOps

### 1. In which layer is identity checked? Which test proves that it does not depend on the prompt?

Identity is checked in the tool layer, inside the MCP server that provides the order tools. The customer's identity is given from the session when the server starts, and no tool takes a customer identity from the model. When an order is requested, the server searches for it only among the orders of the customer in the session. When another customer's order is requested, the answer is exactly the same "not found" as for an order that does not exist. This way, one cannot even tell whether an order with that number exists.

The tests showing that the identity check does not depend on the prompt do not use the model at all. In the first test, 10 foreign orders in different states were asked directly to the three order tools. All 30 calls returned the same "not found" answer as for an order that does not exist. In the second test, an extra customer identity was sent to the MCP server, and it was checked that the extra identity did not change the result. Since the model takes no part in either test, the result does not depend on the prompt. The tests with the model gave the same result; for example, a user who introduced themselves as a system administrator also got the "not found" answer.

In the repo: `src/tools/orders.py`, `src/mcp_servers/shopops_orders.py`, `eval/check_access.py`, `eval/results/access_test.csv`

### 2. How did you handle the difference between customer_id and customer_unique_id?

In the Olist data, every order gets a new customer number. The real person is identified by a second number. The data has 96,096 real people for 99,441 order-level customer numbers. If I had built the session on the order-level number, a customer with more than one order could see only one of their orders.

So I built the session on the number that identifies the real person, customer_unique_id. The order queries link each order to customer_unique_id through the customers table and return only the orders of the person in the session. This way, a customer sees all of their own orders and none of anyone else's. The demo customer in the terminal has 17 orders, and the question "where is my last order?" finds the newest of the 17.

On the operations side, neither number can be shown in a query result. They can still be used for joining, filtering and counting. None of the 8 defined metrics counts customers. So for a question like "how many different customers", choosing the right number is left to the SQL the agent writes itself. I still see the lack of a metric that counts customers as an open point.

In the repo: `src/tools/orders.py`, `src/guardrails/sql_validator.py`

### 3. What did the semantic layer contribute to SQL accuracy? Give an example of a question where the semantic layer was not enough.

The same 8 operations questions were asked to two systems. The system that writes SQL from the table schema alone, without metric definitions, reached the right result in 1 question, and the Ops Data Agent, which uses the metric definitions, in 7. So the semantic layer raised the share of correct results from 12% to 88%. Both systems were measured again on 22 October, and the result was the same.

None of the queries of the system without definitions returned an error; it knows how to write SQL. Where it went wrong was the definitions. It compared "late delivery" by hour instead of by day. Since the estimated delivery date is always stored as midnight in the data, orders delivered in the afternoon of the estimated day looked late, and the rate came out as 8.11% instead of 6.72%. It also added the freight fee to GMV: for January 2018 it found 1,101,920 BRL instead of 945,456 BRL. It also counted orders with more than one item several times. Because the semantic layer fixes definitions such as late delivery, GMV and order counting in one place, the agent does not have to guess the definitions again for each question.

The question where the semantic layer was not enough was: "Is the review score of late orders different from that of orders delivered on time?" There is no metric that splits the review score into late and on-time orders, so the agent wrote its own SQL. Some orders have more than one review; the official definition first averages the score of each order. The agent skipped the per-order averaging step and found 2.2715 instead of 2.2723 for late orders. The difference is small, and with two decimals both are 2.27, but the definition is wrong. The fix could be to add a "late or on time" split to the metrics file. The review score example shows that the semantic layer protects only the questions it defines.

In the repo: `src/knowledge/metrics.yaml`, `eval/results/ops_final.csv`, `eval/results/ops_b2.csv`, `docs/error_analysis.md` items 11 and 12.

### 4. Why is creating a return request behind human approval? Can the LLM imitate the approval token, and why not?

Opening a return request is the only lasting change of records in the system, and it starts a refund to the customer. A request opened with the wrong reason, the wrong amount, or under the influence of a hidden instruction creates a real cost for the company. An example of a request prepared with the wrong reason happened during development: when the customer wrote an ambiguous sentence, the model changed the return reason and the refund amount dropped. What made the error visible was that the customer saw the summary built by code before approving.

Four things make it hard for the model to imitate the approval code. First, the model never sees the approval code. The code is generated at random on the server when the request is prepared and kept on the server; it is not part of the summary that goes to the model. Second, the action that really writes the request is not among the tools the model can use. If the model tries to call the action that writes the request, it gets a "no such tool" answer. Third, only the "Onaylıyorum" ("I approve") button in the interface sends the code to the server; typing "I approve" into the chat does nothing. Fourth, each code can be used only once. Whether the customer approves or declines, the pending request is deleted, and the return rules are checked once more right before the request is written.

The test results point the same way. In the 4 attempts where the model tried to write the request directly, no row was written. In 20 attack runs, no row was written without the customer's approval either. Even in the test with a fake model that fully obeys hidden instructions, nothing was written. Some rules still apply after approval: requests above 500 BRL go to a senior support agent for approval, and a second request cannot be opened for the same order.

In the repo: `src/tools/return_requests.py`, `src/mcp_servers/shopops_orders.py`, `tests/test_agent_approval.py`, `tests/test_indirect_injection.py`

### 5. How did you verify the Turkish summary of Portuguese reviews?

This version has no review summary. The agent that summarises reviews is an advanced-level item in the brief. I preferred to finish the base and target levels completely first. When a user asks for review analysis, the router recognises the request and politely says that review summaries are not part of this version. All of the extra questions in the router test were classified correctly; the questions asking for review analysis are among the extra questions.

The work on reviews has so far stayed on the security side. I wrote a check that flags instructions hidden in reviews. The check caught all 3 attack reviews made up for the test. Of the 42,691 real reviews with text, it flagged none by mistake.

If I had added the summary feature, I would have verified the summaries in three ways. Each theme in a summary would come with a quote from the Portuguese original and the number of that review, so every claim would be tied to a review. I would label 20 to 30 summaries by hand, checking the quotes with a translation tool, and compare the LLM judge's decisions with my own labels. I would also let SQL, not the model, count how many reviews mention each theme, so the numbers would not be left to the model's guess.

In the repo: `src/guardrails/injection_flag.py`, `eval/results/injection_summary.md`

### 6. Which metric must be read with the observational limit in mind, and how did you state this in the answer?

The clearest example is the relationship between late delivery and review score. The average review score of late orders is about 2.27, that of orders delivered on time 4.29. The score difference is not enough to say "late delivery lowers the score". Late orders may also differ in other ways: they may go to different regions, or come from different categories or different sellers. The data is observational, so there is no experiment behind it.

The observational limit is stated in two ways in the answers. Each of the 8 metrics in the metrics file has a warning note. The note of the late delivery rate contains the sentence "Gözlemsel oran; nedensellik değildir" ("Observational rate; not causation"). When a metric runs, the note comes back with the result and is shown under the answer in the demo. The operations agent's instructions also tell it to show the relationship between two things but not to claim cause and effect. In the review score question, the agent showed the difference and also wrote that this does not mean the delay caused the low score. That GMV is not income or profit is also written in the metric's note.

In the repo: `src/knowledge/metrics.yaml`, `src/agents/ops_agent.py`

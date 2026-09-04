# What I'd do differently

I shipped Stride's core loop in six weeks and landed six users in April 2026. These are the decisions I would reverse or time differently next time.

## CI failures need an alert, not a badge

The nightly eval suite ran red for 60 consecutive runs without anyone noticing. I had a badge showing in the README, but a badge is a display artifact, not a notification. By the time I checked the test results, two weeks had gone by and the eval suite had lost trust value.

Next time, I will configure an alert on the first failure and a summary email on the tenth consecutive failure. The badge is useful for downstream users, but the developer needs to know immediately.

## Security review of tool inputs belongs in the first week

For five months, the Strands tools trusted the model's `user_id` directly without tenant-side validation. The model could theoretically emit a different user's ID and read their data. I caught this in code review because I happened to look at the tool signatures, but this should have been a deliberate security audit in week one, not a lucky find.

Next time, I will schedule a threat model review on day three of any agent project, before the first tool is written. I will pair-review all tool inputs and write a tenant-binding test that injects wrong IDs and verifies rejection.

## Tool inputs need typed schemas, not strings

`shared/tools.py` grew to 1,300 lines. Every tool took string arguments; there was no schema enforcement and no IDE hints about what a tool expects. When I refactored the habit decomposition, I had to grep for every call site manually.

Next time, I will define Pydantic models for each tool's input up front and pass them through Strands. The cost is one model per tool, but the gain in maintainability is immediate.

## Measure the slowest path on day one

Twilio's 15-second hard deadline for a TwiML response shaped the entire architecture. I built a REST fallback, added reply-deadline tokens to the prompt, and limited the history to 20 turns — all to stay under 12 seconds. Only after launch did I profile the slowest path: it was a planning-day conversation, hitting 16 seconds at the 99th percentile.

Next time, I will load-test the agent with real-world prompts on day one. I will measure latency on the path that matters most (planning day) before deciding on architecture, not after.

## Observe habits at the beta scale, not in tests

Six users is a tiny cohort, but the data showed a `multiple_questions` pattern: 5 of 46 total replies were replies with more than one distinct question in the text. No unit test would have caught this because the model's reply quality and question-bundling habit depends on the specific user, the session history, and the week structure. Only live data revealed it.

Next time, I will instrument for habit metrics from the first deploy, not three weeks in. I will run an eval suite that checks for these patterns per 50 replies, not per 1,000.

## Start compliance on day one

A2P 10DLC approval took three weeks and gated everything: I could not send proactive messages, could not test the scheduler, and could not invite beta users until the paperwork cleared. The delay was structural, not technical.

Next time, I will file for A2P 10DLC and register consent flows on day one of any SMS project, before writing a single Lambda. The approval window is fixed and unavoidable; the cost is paperwork, not code.

## Ask timezone instead of inferring it

I inferred the user's timezone from their phone's area code during onboarding, saving one message. It worked for four of six users. For two users who had moved, the inferred timezone was wrong, and the first proactive nudge landed at an odd hour (e.g., midnight). I had to ask manually and regenerate the schedule.

Next time, I will ask the user's timezone when the first nudge lands at an hour outside 7 AM – 10 PM local. The follow-up is only needed for people who moved; everyone else saves the message.

## Favor moto over LocalStack

I spent time building a local development environment with LocalStack because it mirrors AWS more closely. But the integration tests ran slower and fewer developers used it. The real tests run with moto, an in-process DynamoDB mock, which is what the CI system actually runs.

Next time, I will use moto for all local development. LocalStack parity is a false goal; the tests that matter run in CI with moto.

# What I'd do differently

These are the decisions I would make differently, written after running a six-user beta in April 2026.

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

Twilio's 15-second hard deadline for a TwiML response shaped the architecture more than any product decision. I built the 12-second cutoff and the REST fallback around it before I had measured a single turn. In the beta the slowest turn took 20 seconds against an average under three, so the fallback ran in production.

Next time I will measure the slowest path first, with real prompts, before deciding how to handle it.

## Observe habits at the beta scale, not in tests

Six users is a tiny cohort, but the data showed a `multiple_questions` pattern: 5 of 46 total replies were replies with more than one distinct question in the text. No unit test would have caught this because the model's reply quality and question-bundling habit depends on the specific user, the session history, and the week structure. Only live data revealed it.

Next time, I will instrument for habit metrics from the first deploy, not three weeks in. I will run an eval suite that checks for these patterns per 50 replies, not per 1,000.

## Start compliance on day one

A2P 10DLC approval took three weeks and gated everything: I could not send proactive messages, could not test the scheduler, and could not invite beta users until the paperwork cleared. The delay was structural, not technical.

Next time, I will file for A2P 10DLC and register consent flows on day one of any SMS project, before writing a single Lambda. The approval window is fixed and unavoidable; the cost is paperwork, not code.

## Ask timezone instead of inferring it

I inferred each user's timezone from their phone's area code during onboarding, which saved one message. It was wrong for people who had moved, and their first proactive nudge landed at an odd hour.

Next time I will ask for the timezone when the first nudge lands at an odd hour. The follow-up is only needed for people who moved; everyone else still saves the message.

## Favor moto over LocalStack

I spent time building a local development environment with LocalStack because it mirrors AWS more closely. But the integration tests ran slower and fewer developers used it. The real tests run with moto, an in-process DynamoDB mock, which is what the CI system actually runs.

Next time, I will use moto for all local development. LocalStack parity is a false goal; the tests that matter run in CI with moto.

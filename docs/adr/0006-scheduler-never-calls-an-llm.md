# 0006. Scheduler Never Calls an LLM

Date: 2026-03-05 · Status: Accepted

## Context

Proactive outbound messages (morning check-in prompts, Friday reviews, midweek nudges) run on a 15-minute timer across all users. If the scheduler called Claude for every candidate user—to compose or approve the message—cost and latency would explode. The scheduler must be cheap and deterministic.

## Decision

The scheduler is pure Python formatting. It queries consented users, evaluates business rules (has the user opted in to reminders? is it their timezone's morning? do they have pending work?), and if a message should send, composes it from a template. Claude is never invoked from the scheduler. The only time the model is called is in response to user input.

## Consequences

The scheduler ran 14,004 times during the beta with zero LLM costs. Proactive copy is templated and testable with unit tests, never requiring expensive evals. The scheduler's latency is predictable—typically 1.0 second for all consented users.

When the user replies to a proactive message, the agent receives session context indicating the turn is a reply to an outbound message (within 6 hours of send). This allows the agent to maintain continuity without the scheduler doing any reasoning. Proactive messages in the beta included 31 nudges (morning 14, evening 9, planning 5, midweek 4, review 4).

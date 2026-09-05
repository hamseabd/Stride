# 0011. Rate Limiter Fails Open

Date: 2026-03-05 · Status: Accepted

## Context

The per-user 50-message-per-day rate limit is enforced via an atomic DynamoDB counter. DynamoDB is also the source of every other application read: projects, tasks, habits, patterns. An outage that affects the rate-limit check also affects the entire application.

## Decision

On a DynamoDB error during the rate-limit check, the message is allowed through. The application does not raise an exception or drop the request. A blocked attempt is logged under the `BLOCKED#` partition with the reason included. Abuse is bounded by SMS opt-in consent and Twilio signature verification.

## Consequences

A database outage degrades gracefully to "no rate limit" rather than "no service". The system remains available even if the counter is unreadable. The tradeoff accepts bounded abuse (a user who consents and passes Twilio verification) in exchange for availability. Blocked attempts are auditable and can be investigated post-incident. The consent flow and Twilio checks remain the primary abuse controls.

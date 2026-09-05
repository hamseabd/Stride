# 0001. SMS Is the Only Interface

Date: 2026-03-01 · Status: Accepted

## Context

Productivity apps compete for time users don't have. Habit research shows that passive applications—those that wait to be opened—fail for busy users who have already abandoned competing tools. Stride's target users are solo developers and founders with concrete, time-bounded goals. They need coaching delivered to them, not coaching they must remember to request.

## Decision

Stride operates exclusively over SMS via Twilio A2P. No app, no login, no web dashboard. Stride initiates contact; users reply. This push model reverses the default: the coach texts first with a time-bound question or observation.

## Consequences

SMS constraints shape every design choice. Replies are capped at 480 characters (3 segments). The Twilio webhook must complete and return TwiML within 15 seconds. User identity is the phone number in E.164 format. TCPA compliance requires explicit opt-in consent before any message. Per-segment SMS cost (~$0.0083 per outbound segment) becomes a meaningful line item.

Pattern data accrues per phone number, not per account or user profile. A read-only web view of historical patterns is the only planned second interface; users will never manage tasks through it. This keeps infrastructure costs low and preserves the async, text-first interaction model.

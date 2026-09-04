# 0003. Haiku Classifier in Front of Sonnet

Date: 2026-03-24 · Status: Accepted

## Context

Inbound SMS from users carry multiple intents. Some are coaching turns that require reasoning—planning, pattern analysis, task decomposition. Others are operational: "remind me later", feedback on a previous message, requests for help on unrelated topics. Routing every message to Claude Sonnet wastes budget.

## Decision

A Haiku classifier intercepts every inbound message. It routes into five intents: `conversation`, `feedback`, `help`, `remind_me`, `no_reminders`. Only `conversation` and `help` are forwarded to Sonnet; the rest are handled by rules or routed elsewhere. On classifier failure, the message defaults to `conversation`.

## Consequences

Cost drops dramatically for routed messages. The classifier costs ~$0.0003 per call; Sonnet coaching costs ~$0.019 per turn—a 63× difference. Measured in the beta, 28% of all messages never reach Sonnet. The intent distribution was conversation 72%, feedback 13%, help 10%, remind_me 3%, no_reminders 2%.

This small classifier step saves $7–8 per 100 users per month. It also improves latency for simple intents. The loss in flexibility is minimal: the classifier trains on examples of all five intents and degrades safely by treating ambiguous cases as coaching turns.

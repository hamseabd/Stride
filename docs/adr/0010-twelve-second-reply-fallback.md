# 0010. Twelve-Second Reply Fallback

Date: 2026-03-24 · Status: Accepted

## Context

Twilio expects a webhook response (TwiML) within 15 seconds or treats the message as unacknowledged. In the beta, Sonnet agent turns took up to 20 seconds when the context was large or the turn was complex. Returning nothing causes Twilio to retry and potentially delivers duplicate messages.

## Decision

Lambda timeout is set to 30 seconds. If the turn finishes under 12 seconds, return TwiML synchronously. If not, queue the message for REST API delivery and return empty TwiML immediately. The same path handles both inbound and onboarding opener messages.

## Consequences

No messages are silently dropped due to webhook timeout. Slow turns incur the cost of one additional outbound SMS via REST. The handler tracks time spent on context assembly, classification, and the agent turn separately. Observability logs both the webhook latency and the eventual REST send time. The 12-second threshold is conservative to account for Twilio processing.

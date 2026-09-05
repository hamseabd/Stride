# 0002. Strands SDK, Not a Hand-Rolled Loop

Date: 2026-03-01 · Status: Accepted

## Context

A raw Anthropic tool loop—parsing tool calls, managing message history, handling async execution—spans 200+ lines of boilerplate. This code is error-prone, rarely tested, and specific to each project. Productizing coaching sessions requires robust message history, structured telemetry, and upgrade safety. Rolling that logic project-by-project is waste.

## Decision

Stride uses the Strands SDK (pinned to 0.1.6). All tools are declared as `@tool` functions in a single module (`shared/tools.py`). The Lambda handler never parses tool calls; the Strands `Agent` manages the loop, message state, and tool invocation.

## Consequences

History is Strands' internal message list, persisted verbatim to DynamoDB. This gives a source of truth independent of any schema migration. Telemetry—token counts, latency, cost per turn—is read from `result.metrics` after each turn, not reconstructed from API responses.

Pinning to 0.1.6 means upgrades are deliberate. The Strands API surface is stable for core agent operations; when a major version lands, it will require code review before adoption. This trade-off accepts slower cadence for safety in a system handling real user data and generating real cost.

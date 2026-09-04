# 0004. Preload Context, Never Let the Agent Fetch

Date: 2026-03-05 · Status: Accepted

## Context

An agent that fetches its own context—calling tools to retrieve user projects, tasks, habits, patterns—spends tool-call cycles and prompt tokens re-learning information that should be stable. This increases latency and cost while complicating debugging: what the model saw is distributed across multiple tool responses.

## Decision

The Lambda handler assembles all context before invoking the agent. Projects, tasks, habits, patterns, timezone, and session state are compiled into the system prompt suffix. The user never appears as mutable context—only as a summary of what they have told Stride before. The agent can reason about this history but cannot request fresh data mid-turn.

## Consequences

Agent behavior becomes predictable. Output is typically 74 tokens per turn. No variability from failed context fetches; no cycles spent on retrieval. The handler owns the data shape, making it a single point to enforce constraints—history length, token budgets, schema versioning.

The prompt suffix is per-user and cannot be cached, but the static system prefix is cached with prompt caching enabled. Average cache efficiency in the beta was 73% of prompt tokens. Cost per coached turn averaged $0.0191.

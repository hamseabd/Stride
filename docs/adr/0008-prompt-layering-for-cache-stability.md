# 0008. Prompt Layering for Cache Stability

Date: 2026-03-24 · Status: Accepted

## Context

Anthropic's prompt caching is cost-effective only when the prompt prefix is byte-identical across multiple calls. Every variation—even a single interpolated value—breaks the cache key and wastes both tokens and money. In Stride, each user has distinct context: projects, tasks, habits, patterns, timezone. Caching a prompt that includes user data would never reuse.

## Decision

The system prompt is split into two parts. The static prefix contains persona, capacity language, SMS rules, and session types. It carries `cache_control: ephemeral` and never includes user-specific data. The dynamic per-user suffix is appended after the prefix is locked and cached; it contains projects, tasks, habits, patterns, session context, and timezone.

## Consequences

In the beta, 73 % of prompt tokens were served from cache across 46 coached turns. Cache savings offset the cost of Haiku classification and approach zero LLM spend for the scheduler. The prefix must never interpolate `user_id`, project names, or any variable. Prompt version is logged with every turn so cache behavior can be audited. Cache invalidation is the developer's responsibility; the model has no way to signal a stale prefix.

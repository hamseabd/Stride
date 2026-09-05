# Prompt design

Stride's system prompt is divided into three layers that separate static, cacheable content from dynamic, user-specific context. This design achieves 73 % cache reuse during the beta, reducing inference cost and latency.

## Three layers

The full prompt delivered to Claude consists of three concatenated pieces:

**Layer 1: Persona.** `STRIDE_SYSTEM_PROMPT` in `shared/prompt.py` — who Stride is, core sessions, internal estimates, scope boundaries.

**Layer 2: SMS rules.** `_CAPACITY_LANGUAGE_ADDENDUM` and `_SMS_SYSTEM_ADDENDUM` in `functions/sms/handler.py` — message length tiers (160/320/480 chars), no emojis/markdown/jargon, one question per message, decomposition flow, planning day, habit tracking.

**Layer 3: Per-user context.** `_build_user_context()` builds dynamic suffix with date, timezone, tone, name, goals, habits, patterns, session context, and instruction not to re-fetch.

**Layer 4: Onboarding addendum.** `_ONBOARDING_ADDENDUM` (new users only) — adaptive flow, handling vague goals, name/timezone collection.

Layers 1 and 2 are cached together with `cache_control: ephemeral`. Layer 3 is dynamic and not cached. Layer 4 is appended only once per user lifecycle.

## Why the split

[ADR-0008](adr/0008-prompt-layering-for-cache-stability.md) documents this design. Layers 1–2 form a static, cacheable prefix that never changes across users or turns. By separating static from dynamic, Stride achieves 73 % cache reuse (46 coached turns, avg 5,602 cache-read tokens vs. 2,054 fresh tokens). Cache savings offset Haiku classification costs and make the scheduler nearly free; without caching, the beta volume would cost 10x as much.

## What the user context contains

The per-user suffix built by `_build_user_context()` includes:

- Today's ISO date
- User's timezone (stored, or inferred from area code for new users)
- User's name and coaching tone preference (balanced, direct, encouraging)
- Active goals (with cycles, deadlines, days remaining, tasks, velocity history)
- Backlog goals (saved but not yet planned)
- Habits (title, frequency, current streak, done-today status)
- Patterns (completion rate, common blockers if 3+ weeks of data)
- Session context (if replying to proactive message within 6 hours, what type)
- Instruction not to re-fetch (pre-loaded; don't call list_active_projects, get_cycle_data, etc.)

## Length and style rules

The exact rules enforced on every SMS response, quoted from `_SMS_SYSTEM_ADDENDUM` in `functions/sms/handler.py`:

```
You are responding via SMS. These rules are non-negotiable.

ONE QUESTION PER MESSAGE. Never combine two questions in one text.
Bad: "What's your goal? And when do you want it done by?"
Good: "What's a big project you want to make progress on?"
Wait for their reply before asking the next thing.

MESSAGE LENGTH:
Quick replies and single questions: aim for 160 chars (1 text).
Check-ins and planning questions: up to 320 chars (2 texts).
Reviews and summaries: up to 480 chars max (3 texts, hard limit).
Shorter is always better. Never exceed 480 characters.

FORMATTING:
No markdown, no bold, no headers, no asterisks, no emojis.
No bullet points or numbered lists.
For task rundowns, use plain line breaks with one task per line.
Plain sentences and short paragraphs only.

Never expose internal IDs, error messages, or technical details.
If you need to share more, give the key point and ask if they want detail.
```

The validator in `shared/validators.py` logs warnings (but never blocks) for length, jargon, size-label leaks, or multiple questions.

## Versioning

`PROMPT_VERSION` in `shared/prompt.py` is `v2.0` and is bumped on material changes. Every agent invocation logs `agent_metrics` with version and token counts, allowing any turn to be correlated with its exact prompt.

## What the evals check

**L1 deterministic checks** (gate every PR, run in <5 seconds, no LLM calls):
- L1.1: Response ≤ 480 characters
- L1.2: No framework jargon (agile-specific terms forbidden in user-facing text)
- L1.3: No raw "XL" size label leaked to the user
- L1.4: ≤ 1 question mark per response
- L1.5: Response is non-empty
- L1.6: Tool call inputs have all required arguments (anti-drift guard across 21 tools)
- L1.7: UUIDs in tool arguments exist in seeded fixture state (no hallucinated IDs)
- L1.8: Response contains no PII (email, phone, address)
- L1.9: `complete_onboarding` fires after project + cycle + task are created
- L1.10: ≤ 6 tool calls per turn (runaway loop prevention)
- L1.11: Date fields are valid ISO and not in the past
- L1.12: Classifier recall ≥ 0.95 per intent across 40 labeled pairs

**L2 cross-family judge** (nightly, Amazon Nova Pro via Bedrock — separate model family to avoid self-preference bias):
- L2.1: Tool selection correctness
- L2.2: Coaching tone alignment with user preference and context

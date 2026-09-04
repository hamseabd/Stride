# Prompt design

Stride's system prompt is divided into three layers that separate static, cacheable content from dynamic, user-specific context. This design achieves 73 % cache reuse during the beta, reducing inference cost and latency.

## Three layers

The full prompt delivered to Claude consists of three concatenated pieces:

**Layer 1: Persona and capacity language.** `STRIDE_SYSTEM_PROMPT` in `shared/prompt.py` defines who Stride is: a coach who helps people finish multi-week goals via SMS, without jargon. It explains the core sessions (planning day, daily check-ins, weekly reviews), how estimates work internally, and how to redirect users who ask for help outside Stride's scope. This layer is identical for every user and every turn.

**Layer 2: SMS rules and decomposition language.** `_CAPACITY_LANGUAGE_ADDENDUM` and `_SMS_SYSTEM_ADDENDUM` in `functions/sms/handler.py` specify the technical constraints for SMS: message length tiers (160/320/480 characters), no emojis, no markdown, no internal jargon, one question per message. This layer also describes how to handle goal decomposition, new goals after onboarding, planning day flow, habit tracking, and Friday reviews. Static, identical for all users.

**Layer 3: Per-user context suffix.** `_build_user_context()` in `functions/sms/handler.py` builds a dynamic suffix containing today's date, the user's timezone, coaching tone preference, name, inferred timezone from their area code (for new users), active and backlog goals, current cycle tasks with estimates, velocity history, habits with streaks, patterns (completion rate, common blockers), and session context if the user is replying to a proactive message within the 6-hour staleness window. This suffix also includes an instruction not to re-fetch any of these data points, since they were pre-loaded before the agent was invoked.

**Layer 4 (new users only): Onboarding addendum.** `_ONBOARDING_ADDENDUM` is appended only if `is_new_user=True`. It runs through the adaptive onboarding flow, explains how to handle vague goals and multiple goals at once, and sets expectations for name and timezone collection. Omitted for returning users.

Layers 1 and 2 are cached together with `cache_control: ephemeral`. Layer 3 is dynamic and not cached. Layer 4 is appended only once per user lifecycle.

## Why the split

[ADR-0008](adr/0008-prompt-layering-for-cache-stability.md) documents this design. By keeping persona and rules in an immutable static prefix, Stride reuses 73 % of prompt tokens across all users and turns during the beta (46 coached turns, average 5,602 cache-read tokens per turn vs. 2,054 fresh input tokens). This cache ratio is only possible because the prefix never interpolates user_id, project names, dates, or any variable data.

Cache savings offset the cost of Haiku classification (the fast intent router) and make the 14 daily scheduler runs across 6 users nearly free. Without caching, the same volume would cost 10x as much.

## What the user context contains

The per-user suffix built by `_build_user_context()` includes:

- Today's ISO date
- User's timezone (stored preference, or inferred from phone area code for new users)
- User's name (if set)
- User's coaching tone preference (balanced, direct, or encouraging)
- Inferred timezone from the user's phone area code (new users only, for confirmation)
- **Active goals:** projects with active cycles, deadlines, days remaining, phase plans, current cycle tasks with human-readable time estimates, and velocity history (weeks completed, tasks delivered vs. planned)
- **Backlog goals:** projects without active cycles, awaiting planning
- **Habits:** title, frequency, current streak, done-today status
- **Patterns:** completion rate as percentage, common blockers (if 3+ weeks of data), low-completion-rate flag (if <60% and 3+ weeks of history)
- **Session context:** if the user is replying to a proactive message within 6 hours, the type of message (morning check-in, Friday review, etc.) is noted so the agent can respond in context
- **Instruction to not re-fetch:** an explicit note that all data was pre-loaded and the agent must not call list_active_projects, get_cycle_data, get_user_patterns, get_pace_history, or list_habits

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

The validator in `shared/validators.py` logs warnings (but never blocks) if a response exceeds 480 chars, contains scrum jargon, leaks size labels like "XL", or contains more than one question mark. These are advisory; the response is still sent.

## Versioning

`PROMPT_VERSION` in `shared/prompt.py` is set to `v2.0` and bumped whenever the system prompt changes materially. Every agent invocation logs `agent_metrics` with the prompt version, `input_tokens`, `output_tokens`, `cache_read_tokens`, and `cache_write_tokens`. This allows any turn to be correlated with the exact prompt that produced it, essential for auditing cache behavior and performance changes across prompt iterations.

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

**L2 cross-family judge** (nightly cron, Amazon Nova Pro via Bedrock):
- L2.1: Tool selection is correct and necessary (does the agent call the right tools with the right arguments?)
- L2.2: Coaching tone matches user preference and session context (is the response empathetic, direct, or encouraging as appropriate?)

The L2 judge runs on a separate model family (Amazon Nova Pro, not Claude) to avoid self-preference bias and to calibrate against real user conversations from production.

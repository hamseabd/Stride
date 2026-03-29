import base64
import os
import time
from datetime import date
from urllib.parse import parse_qs

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from strands import Agent
from strands.models.anthropic import AnthropicModel

from shared.prompt import STRIDE_SYSTEM_PROMPT, PROMPT_VERSION
from shared.guards import check_message, check_rate_limit
from shared.classifier import classify_intent
from shared.validators import validate_response, MAX_SMS_CHARS
from shared.db import (
    log_blocked_attempt,
    get_consent, record_consent, revoke_consent,
    record_proactive_consent, revoke_proactive_consent,
    get_or_create_user, set_onboarded,
    get_conversation, save_conversation,
    store_feedback,
    get_latest_outbound, set_outbound_replied,
)
from shared.tools import (
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
    submit_feedback,
)

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()

SMS_MAX_CHARS = 1600   # Twilio hard limit (safety net in _twiml)

TOOLS = [
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
    submit_feedback,
]

_OPT_IN_PROMPT = (
    "Hey! I'm Stride \u2014 I help you finish what you start.\n"
    "Reply YES to get started.\n"
    "Reply STOP anytime to unsubscribe."
)
_WELCOME = (
    "You're in! I'm Stride. "
    "Tell me one goal you want to make progress on and I'll help you get there."
)
_UNSUBSCRIBED = (
    "You've been unsubscribed from Stride. "
    "Text us again anytime to re-join."
)
_BLOCKED_REPLY = (
    "I'm Stride \u2014 I help with your goals and plans.\n"
    "Want to set a goal, check in, or update your plan?"
)
_ERROR_REPLY = "Something went wrong. Try again in a moment."

_SMS_SYSTEM_ADDENDUM = """
You are responding via SMS. Critical rules:
- ONE QUESTION PER MESSAGE. Never combine two questions in one text.
  Bad: "What's your goal? And when do you want it done by?"
  Good: "What's one thing you want to finish or make real progress on?"
  Then WAIT for their reply before asking the next thing.
- Keep every reply under 300 characters when possible.
- Never use markdown, bullet points, numbered lists, or any formatting.
- Plain sentences only. Short paragraphs are ok.
- Never expose internal IDs, error messages, or technical details.
- If you need to share more info, send the most important part and ask if they want detail.
"""

_ONBOARDING_ADDENDUM = """
NEW USER — no projects yet. Run setup.

CRITICAL: ONE QUESTION PER MESSAGE. Never send two questions in one text.
SMS users drop off when they get a wall of text. Ask one thing. Wait. Ask the next.

Onboarding sequence:
1. "Hey! I'm Stride, your productivity coach. What should I call you?"
2. Wait for name. "Nice to meet you, {name}! What timezone are you in?"
   (If they say a city, use set_user_preference with the IANA timezone.)
3. "What's one thing you want to finish or make real progress on?"
4. Wait for their goal. "When do you want that done by?"
   (If no deadline, suggest one: "Let's aim for [reasonable timeframe]?")
5. Now DECOMPOSE the goal:
   - First ask: "What feels like the first step to you?"
   - Wait for their answer. Use their instinct as the starting point.
   - Then propose the full structure: "Smart — [validate their idea]. I'd do
     something like: 1) [phase based on their input], 2) [phase], 3) [phase].
     Sound right?"
   - Call create_project with the goal name, target_date, and a description
     containing the 2-3 phases.
6. Wait for confirmation. Then plan THIS WEEK:
   - "Let's get started. For this week, I think these make sense:"
   - Create a work cycle (this week's dates, goal = phase 1 description).
   - Create 2-3 tasks. Tell the user what you're creating and roughly how long
     each will take (time language, never S/M/L/XL).
7. "Any daily habits you want to build — like writing, exercise, or reading?"
   Use create_habit if yes. If they say no, that's fine.
8. Call complete_onboarding.
9. "I'll check in tomorrow morning to see how it's going. Reply REMIND ME
   to get daily check-ins from me."

Keep each reply under 160 chars when possible — 1 SMS segment.
Never mention 'points', 'sprints', or 'stories'. Never show S/M/L/XL.

IMPORTANT: The user's first week plan is created NOW, during onboarding.
They should leave this conversation with a project, a phase plan, 2-3 tasks
for the week, and optionally a habit or two. They're ready to go.
"""

_CAPACITY_LANGUAGE_ADDENDUM = """
CRITICAL — how you talk about workload:
- NEVER say "S", "M", "L", "XL", "small", "medium", "large", "points", "pts", or "story points".
- NEVER say "I'll mark that as M" or "That's an L task." The user must not see the sizing system.
- Always use time language: "a few hours", "a day or two", "most of the week", "more than a week".
- Talk about capacity in days: "You usually get about 3 good days of work done per week" (not "15 points").
- When a user is over-planned: "That's about 5 days of work for a 3-day week. What can wait?"
- The estimate and point system exists internally for tracking. Users must NEVER see any part of it.

GOAL DECOMPOSITION — how to break down a goal (used during onboarding AND on-demand planning):
When planning a goal (e.g. "launch my portfolio", "save $5K", "get 10 clients"):
1. Confirm it: restate it back to make sure you understand.
2. Ask for a deadline: "When do you want that done by?" If no deadline, suggest one
   together: "Let's aim for 6 weeks from now?"
3. Propose 2-3 phases: "I'd break that into: 1) [phase], 2) [phase], 3) [phase]. Sound right?"
4. Store the phases: call create_project with the phase plan in the description field, e.g.
   description="Phase 1: Research and pick template (week 1). Phase 2: Write all content (weeks 2-3). Phase 3: Go live and share (week 4)."
5. Focus on THIS WEEK: "Let's plan this week. For phase 1, I think these make sense:" then
   propose 2-3 concrete tasks and create them.
6. Never dump all phases as tasks. One week at a time. Future phases are in the plan, not the task list.

NEW GOALS — capture vs plan:
When a user mentions a new goal AFTER onboarding:
- Save it immediately: call create_project with the name (and deadline if they mention one).
- Then ask: "Want to break this down and plan now, or should I bring it up on your next
  planning day?"
- If they want to plan now: run the full decomposition flow above (phases, cycle, tasks).
- If they want to wait: leave it as a backlog goal. No cycle, no tasks yet.
- On planning day, surface all backlog goals: "You also have 'YouTube channel' saved —
  want to start planning that this week?"

BACKLOG vs ACTIVE GOALS:
- A goal WITH an active work cycle = active (being worked on this week).
- A goal WITHOUT a work cycle = backlog (saved, waiting to be planned).
- The pre-loaded context labels both clearly. Reference backlog goals on planning day.
- Never create a work cycle for a backlog goal unless the user explicitly asks to plan it.

MULTIPLE ACTIVE GOALS:
- Users can have multiple active goals at the same time. Each is a separate project.
- When planning or checking in, reference all active goals: "You've got two things going —
  the portfolio and the blog. What's the focus this week?"
- If a user mentions a new goal mid-conversation, create a new project. Don't merge it into
  an existing one unless they ask.

PLANNING DAY (Monday or user-configured):
- Review each active goal: last week's progress, this week's focus.
- Surface backlog goals: "You also have [X] and [Y] saved. Want to activate one of those?"
- For each active goal: create a new work cycle with tasks for the week. Reference the phase
  plan from the project description to pick the right focus.
- Let the user decide priorities: "Which goals are the main focus this week?"

WHEN THE WEEK IS ALREADY PLANNED (user already has tasks):
- If a user already has tasks for the week and texts you, don't re-plan. Help them with
  what they have — check in, update status, work through blockers.

HABITS — separate from goals:
- Habits are recurring practices: "Write 30 min daily", "Exercise 3x/week", "Read before bed".
- Use create_habit for these, NOT create_task.
- Habits have streaks. Celebrate milestones: "5 days in a row writing — nice!"
- In morning check-ins, mention both tasks and habits.
- In Friday reviews, include habit streaks: "You wrote 5 of 7 days this week."
- If a streak breaks, be encouraging: "Missed yesterday — want to get back on it today?"

FRIDAY REVIEWS — what to include:
- Tasks: X of Y done, name the ones that got done and the ones that didn't.
- Goal progress: reference the phase plan. "You're in Phase 1 of the portfolio.
  You've been at it for 2 weeks with 35 days until the deadline."
- Habits: streak summary for each habit.
- One pattern: something you notice (overcommitting, avoiding certain tasks, blockers recurring).
- One suggestion: something concrete to try next week.
"""


def _get_body(event: dict) -> str:
    """Decode the event body, handling API Gateway v2 base64 encoding."""
    raw = event.get("body", "")
    if event.get("isBase64Encoded"):
        return base64.b64decode(raw).decode()
    return raw


def _validate_twilio(event: dict) -> bool:
    """Validate that the request genuinely came from Twilio."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not set — skipping signature validation")
        return True

    validator = RequestValidator(auth_token)
    headers = event.get("headers", {})
    signature = headers.get("x-twilio-signature", "") or headers.get("X-Twilio-Signature", "")
    url = (
        "https://"
        + event.get("requestContext", {}).get("domainName", "")
        + event.get("rawPath", "/sms")
    )
    params = {
        k: v[0] if isinstance(v, list) else v
        for k, v in parse_qs(_get_body(event)).items()
    }
    return validator.validate(url, params, signature)


def _twiml(text: str) -> dict:
    """Wrap text in a TwiML HTTP response, truncating at SMS_MAX_CHARS."""
    if len(text) > SMS_MAX_CHARS:
        # Truncate at last sentence boundary before the limit
        truncated = text[:SMS_MAX_CHARS]
        last_period = max(
            truncated.rfind(". "),
            truncated.rfind(".\n"),
            truncated.rfind("? "),
            truncated.rfind("! "),
        )
        text = truncated[: last_period + 1] if last_period > 0 else truncated
    response = MessagingResponse()
    response.message(text)
    return Response(
        status_code=200,
        content_type="text/xml",
        body=str(response),
    )


# Estimate labels for context building (internal → user-facing)
_ESTIMATE_LABELS = {
    "S": "a few hours", "M": "a day or two",
    "L": "most of the week", "XL": "more than a week",
}

# Static system prompt prefix — identical for all users, cached by Anthropic API
_STATIC_PREFIX = (
    STRIDE_SYSTEM_PROMPT.strip()
    + _CAPACITY_LANGUAGE_ADDENDUM
    + _SMS_SYSTEM_ADDENDUM
)


def _build_user_context(user_id: str, user: dict, is_new_user: bool) -> str:
    """
    Pre-load all user context into a string for the system prompt.
    Constraint #20: the agent never fetches its own context.
    """
    tz = user.get("timezone", "America/New_York")
    tone = user.get("preferred_tone", "balanced")
    name = user.get("name", "")

    lines = [
        f"\nCurrent user_id: {user_id}",
        f"User's timezone: {tz}",
        f"Coaching tone: {tone}",
    ]
    if name:
        lines.append(f"User's name: {name}")

    # --- Pre-load projects + tasks (split active vs backlog) ---
    projects = list_active_projects(user_id=user_id)
    if "error" not in projects and projects.get("projects"):
        active_goals = []
        backlog_goals = []

        for p in projects["projects"]:
            if p.get("active_cycle"):
                active_goals.append(p)
            else:
                backlog_goals.append(p)

        if active_goals:
            lines.append("\nActive goals:")
            for p in active_goals:
                due = f" (due {p['target_date']})" if p.get("target_date") else ""
                lines.append(f"- {p['name']}{due}")

                # Phase plan from description
                if p.get("description"):
                    lines.append(f"  Plan: {p['description']}")

                # Days remaining until deadline
                if p.get("target_date"):
                    try:
                        target = date.fromisoformat(p["target_date"])
                        days_left = (target - date.today()).days
                        if days_left > 0:
                            lines.append(f"  Deadline: {days_left} days away")
                        elif days_left == 0:
                            lines.append("  Deadline: TODAY")
                        else:
                            lines.append(f"  Deadline: {abs(days_left)} days overdue")
                    except ValueError:
                        pass

                # Current cycle tasks
                cycle = p["active_cycle"]
                cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
                if "error" not in cycle_data:
                    for task in cycle_data.get("tasks", []):
                        est = _ESTIMATE_LABELS.get(task.get("estimate_label", ""), "")
                        est_str = f" ({est})" if est else ""
                        lines.append(f"  - {task.get('title', '?')}{est_str} [{task.get('status', '?')}]")

                # Velocity history (overall progress toward goal)
                pace = get_pace_history(project_id=p["project_id"], num_cycles=5)
                if "error" not in pace and pace.get("cycle_records"):
                    records = pace["cycle_records"]
                    total_delivered = sum(r.get("delivered_points", 0) for r in records)
                    total_planned = sum(r.get("planned_points", 0) for r in records)
                    lines.append(f"  History: {len(records)} weeks completed, {total_delivered}/{total_planned} tasks delivered")

        if backlog_goals:
            lines.append("\nBacklog (saved, not yet planned):")
            for p in backlog_goals:
                due = f" (due {p['target_date']})" if p.get("target_date") else "(no deadline)"
                desc = f" — {p['description']}" if p.get("description") else ""
                lines.append(f"- {p['name']} {due}{desc}")

        if not active_goals and not backlog_goals and not is_new_user:
            lines.append("\nNo goals yet.")
    elif not is_new_user:
        lines.append("\nNo goals yet.")

    # --- Pre-load habits ---
    habits = list_habits(user_id=user_id)
    if "error" not in habits and habits.get("habits"):
        lines.append("\nHabits:")
        for h in habits["habits"]:
            done = "done today" if h.get("done_today") else "not done today"
            lines.append(f"- {h['title']} ({h['frequency']}, streak: {h.get('current_streak', 0)}, {done})")

    # --- Pre-load patterns ---
    patterns = get_user_patterns(user_id=user_id)
    if "error" not in patterns and patterns.get("found"):
        rate = patterns.get("avg_completion_rate", 0)
        blockers = patterns.get("common_blockers", [])
        count = patterns.get("cycle_count", 0)
        lines.append(f"\nPatterns ({count} weeks of data):")
        lines.append(f"- Avg completion rate: {int(float(rate) * 100)}%")
        if blockers:
            lines.append(f"- Common blockers: {', '.join(str(b) for b in blockers)}")
        if float(rate) < 0.6 and count >= 3:
            lines.append("- NOTE: completion rate is low. Gently address this — help them plan more realistically.")

    # --- Instruction to avoid redundant tool calls ---
    lines.append("\nThis context is pre-loaded and current. Do NOT call list_active_projects, get_cycle_data,")
    lines.append("get_user_patterns, get_pace_history, or list_habits to re-fetch it. Only call write tools (create_task, etc).")

    # --- Onboarding addendum ---
    if is_new_user:
        lines.append(_ONBOARDING_ADDENDUM)

    return "\n".join(lines)


def _call_agent(user_id: str, message: str, is_new_user: bool, user: dict) -> str:
    """Run the Stride agent for an SMS message. Returns the reply string."""
    planning_day = int(user.get("planning_day", 1))
    tz = user.get("timezone", "America/New_York")

    # P0: Pre-load all user context (constraint #20)
    dynamic_suffix = _build_user_context(user_id, user, is_new_user)

    history = get_conversation(user_id)

    # P1: Prompt caching — static prefix is cached (90% cheaper), dynamic suffix is not
    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
    model.update_config(params={
        "system": [
            {"type": "text", "text": _STATIC_PREFIX, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_suffix},
        ]
    })

    agent = Agent(model=model, tools=TOOLS, messages=history)

    t0 = time.monotonic()
    result = agent(message)
    agent_duration_ms = round((time.monotonic() - t0) * 1000)

    save_conversation(user_id, agent.messages, planning_day=planning_day, user_timezone=tz)

    # --- Telemetry: log Strands metrics for analysis ---
    reply = str(result)
    try:
        usage = result.metrics.accumulated_usage
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        # Cost estimate (claude-sonnet-4-6: $3/$15 per MTok, cache read 10%, cache write 125%)
        cost_usd = (
            (input_tokens * 3) + (output_tokens * 15)
            + (cache_read * 0.30) + (cache_write * 3.75)
        ) / 1_000_000

        logger.info("agent_metrics",
                     user_id=user_id,
                     prompt_version=PROMPT_VERSION,
                     input_tokens=input_tokens,
                     output_tokens=output_tokens,
                     cache_read_tokens=cache_read,
                     cache_write_tokens=cache_write,
                     total_tokens=usage.get("totalTokens", 0),
                     agent_latency_ms=agent_duration_ms,
                     agent_cycles=result.metrics.get_summary().get("total_cycles", 0),
                     estimated_cost_usd=round(cost_usd, 6),
                     reply_length=len(reply),
                     is_new_user=is_new_user)
    except Exception:
        logger.warning("Failed to extract agent metrics")

    return reply


@app.post("/sms")
def sms():
    """
    POST /sms — Twilio SMS webhook (form-encoded).

    Guard chain:
      1. Twilio signature validation
      2. Parse user_id (From) + message (Body)
      3. Message length / empty check
      4. Per-user daily rate limit (50 msgs/day)
      5. STOP keyword → revoke all consent (exact match, carrier requirement)
      6. Consent check → opt-in prompt or record YES → welcome
      7. Haiku classifier → feedback / remind_me / no_reminders / help / conversation
      8. Track replied_at on latest outbound
      9. User bootstrap (get or create USER# record)
     10. Onboarding detection (auto-complete if projects exist)
     11. Stride agent (Sonnet)
    """
    event = app.current_event._data  # raw API GW event

    # 1. Twilio signature validation
    if not _validate_twilio(event):
        logger.warning("Invalid Twilio signature")
        return Response(status_code=403, content_type="text/plain", body="Forbidden")

    # 2. Parse fields
    body    = parse_qs(_get_body(event))
    user_id = body.get("From", ["unknown"])[0]
    message = body.get("Body", [""])[0].strip()

    logger.info("SMS received", user_id=user_id)

    # 3. Message validation
    msg_check = check_message(message)
    if msg_check is not None:
        logger.info("Message blocked", user_id=user_id, reason=msg_check)
        log_blocked_attempt(user_id, msg_check, message)
        return _twiml(_BLOCKED_REPLY)

    # 4. Rate limit
    if check_rate_limit(user_id):
        logger.info("Rate limit exceeded", user_id=user_id)
        log_blocked_attempt(user_id, "rate_limit", message)
        return _twiml(_BLOCKED_REPLY)

    msg_upper = message.upper().strip()

    # 5. STOP keyword — revoke ALL consent immediately
    if msg_upper == "STOP":
        revoke_consent(user_id)
        revoke_proactive_consent(user_id)
        logger.info("User unsubscribed", user_id=user_id)
        return _twiml(_UNSUBSCRIBED)

    # 6. Consent check
    consent = get_consent(user_id)
    consent_active = consent is not None and consent.get("status") == "active"

    if not consent_active:
        if msg_upper == "YES":
            record_consent(user_id=user_id, phone=user_id)
            logger.info("New user welcomed", user_id=user_id)
            return _twiml(_WELCOME)
        else:
            logger.info("Sending opt-in prompt", user_id=user_id)
            return _twiml(_OPT_IN_PROMPT)

    # 7. Haiku intent classifier — understands natural language
    try:
        intent = classify_intent(message)
    except Exception:
        logger.exception("classify_intent crashed", user_id=user_id)
        intent = "conversation"
    logger.info("Intent classified", user_id=user_id, intent=intent)

    if intent == "feedback":
        store_feedback(user_id, message, source="classifier")
        return _twiml("Thanks for the feedback — I'll pass it along to the team.")

    if intent == "remind_me":
        record_proactive_consent(user_id)
        return _twiml("You'll get daily check-ins! Reply NO REMINDERS to stop.")

    if intent == "no_reminders":
        revoke_proactive_consent(user_id)
        return _twiml("Got it — no more reminders. Text me anytime.")

    # intent is "help" or "conversation" — route to Sonnet agent

    # 8. Track replied_at on latest outbound (for tone derivation)
    try:
        latest_out = get_latest_outbound(user_id)
        if latest_out and not latest_out.get("replied_at"):
            set_outbound_replied(user_id, latest_out["sk"])
    except Exception:
        logger.exception("outbound reply tracking failed", user_id=user_id)

    # 9. User bootstrap
    user = get_or_create_user(user_id=user_id, phone=user_id)
    if "error" in user:
        logger.error("get_or_create_user failed", user_id=user_id, error=user["error"])
        return _twiml(_ERROR_REPLY)

    # 10. Onboarding detection — auto-complete if user has projects but isn't marked
    is_new_user = not user.get("onboarded", False)
    if is_new_user:
        projects = list_active_projects(user_id=user_id)
        if projects.get("projects"):
            is_new_user = False
            set_onboarded(user_id)
            logger.info("Auto-completed onboarding", user_id=user_id)

    logger.info("Routing to agent", user_id=user_id, is_new_user=is_new_user)

    # 11. Stride agent
    try:
        reply = _call_agent(user_id=user_id, message=message, is_new_user=is_new_user, user=user)
        warnings = validate_response(reply)
        if warnings.get("empty"):
            reply = _ERROR_REPLY
        elif warnings.get("length_exceeded"):
            truncated = reply[:MAX_SMS_CHARS]
            last_break = max(
                truncated.rfind(". "), truncated.rfind(".\n"),
                truncated.rfind("? "), truncated.rfind("! "),
            )
            reply = truncated[:last_break + 1] if last_break > 0 else truncated
        return _twiml(reply)
    except Exception:
        logger.exception("SMS agent call failed", user_id=user_id)
        return _twiml(_ERROR_REPLY)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)

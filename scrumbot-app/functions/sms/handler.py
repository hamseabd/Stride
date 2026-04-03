import base64
import os
import time
from datetime import date, datetime, timezone as _tz
from urllib.parse import parse_qs

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from strands import Agent
from strands.models.anthropic import AnthropicModel

from shared.sms import send_sms
from shared.prompt import STRIDE_SYSTEM_PROMPT, PROMPT_VERSION
from shared.timezone import infer_timezone_from_phone, TZ_DISPLAY_NAMES


class _CachedAnthropicModel(AnthropicModel):
    """AnthropicModel subclass that tracks cache token metrics.

    Strands v0.1.6 drops cache_creation_input_tokens and cache_read_input_tokens.
    This override accumulates them on the model instance for telemetry.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0

    def format_chunk(self, event):
        if event.get("type") == "metadata":
            usage = event.get("usage", {})
            self.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
            self.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
        return super().format_chunk(event)
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
    resolve_date,
    create_project, update_project, archive_project,
    create_work_cycle, list_active_projects,
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
    resolve_date,
    create_project, update_project, archive_project,
    create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
    submit_feedback,
]

_OPT_IN_PROMPT = (
    "Hey! I'm Stride.\n\n"
    "I help you finish what you start.\n\n"
    "Reply YES to get started.\n"
    "Reply STOP anytime to opt out."
)
_WELCOME = "You're in!"
_UNSUBSCRIBED = (
    "You've been unsubscribed.\n\n"
    "Text START anytime to re-join."
)
_WELCOME_BACK = (
    "Welcome back! Tell me what you want to finish — a project, a big goal, "
    "anything that takes more than three weeks. I'll help you break it down, plan "
    "each week, and check in daily to keep you on track.\n\n"
    "What's the most important thing you're working on?"
)
_BLOCKED_REPLY = (
    "Hey, I'm Stride.\n\n"
    "Want to set a goal, check in, or update your plan?"
)
_TOO_LONG_REPLY = (
    "That's a lot to take in! I work best one goal at a time.\n\n"
    "Send me your most important goal first and we'll go from there."
)
_ERROR_REPLY = "Something went wrong. Try again in a moment."

_SMS_SYSTEM_ADDENDUM = """
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
"""

_ONBOARDING_ADDENDUM = """
NEW USER — run onboarding. One question per message. Keep each reply under 320 chars.

FIRST MESSAGE:
If the user's message is "[USER_OPTED_IN]", this is their very first interaction.
Send this welcome EXACTLY (do not shorten or rephrase):
"Hey! I'm Stride. Tell me what you want to finish — a project, a big goal,
anything that takes more than three weeks. I'll help you break it down, plan each
week, and check in daily to keep you on track. Just text me like you'd text
a friend — one goal at a time. Reply REMIND ME anytime for daily check-ins.
What should I call you?"

ADAPTIVE ONBOARDING:
Onboarding is NOT a rigid sequence. You need to collect these things before the user
is fully set up:
  - Name (via set_user_preference)
  - Timezone confirmed (via set_user_preference — pre-loaded context has a guess)
  - At least one goal saved (via create_project or create_habit)
  - Onboarding marked complete (via complete_onboarding)

Collect these naturally based on what the user gives you. If they jump straight to
goals before giving their name, ROLL WITH IT — acknowledge the goal, work with it,
and circle back to name/timezone later. Never ignore what the user just said to
force a different question.

PRIORITY: Always respond to what the user just said FIRST. If they shared a goal
(or anything goal-like), engage with THAT before asking for name or timezone.
Name and timezone can always wait — momentum on their goal cannot.

HANDLING GOALS:
- CONCRETE goal (clear finish line, multi-week): ask a follow-up
  ("When do you want that done by?") then save it with create_project.
- MULTIPLE goals at once: acknowledge all of them, then work through them
  one at a time. Pick the most concrete one first. For each goal, ask one
  clarifying question (deadline or scope), then save it.
- HABIT (gym, prayer, meditation, daily routine): save it with create_habit,
  not create_project. Say: "I'll track that as a daily habit." Then move on.
- TOO SMALL (same-day errand, a few hours of work): gently redirect.
  "I'm best with bigger stuff — things that take weeks or months. Got anything
  like that?"
- VAGUE (like "get my life together", "be more productive", "set rules on my
  schedule"): Do NOT just accept it and move on. These aren't goals yet — they're
  wishes. Help the user turn it into something concrete by asking what it would
  look like when done:
  "I hear you — what's one specific thing that would make you feel like you're
  on track? Like finishing a project, hitting a fitness goal, or paying off debt?"
  Keep asking until you get something with a clear finish line.

TIMEZONE:
The pre-loaded context includes a timezone guess from the user's area code.
When there's a natural pause (after saving first goal, or when they give their
name), confirm it briefly: "By the way, you're in {timezone_display} right?"
Don't make timezone its own separate step — slip it in naturally.

CLOSING ONBOARDING:
Once you have name + timezone + at least one goal saved:
  - Call complete_onboarding.
  - If there are more goals to process, keep going.
  - When all goals are captured: "Want to break any of these down and plan your
    week? Or I can bring them up Monday."
  - After planning (or if they defer): "Reply REMIND ME if you want daily
    check-ins from me."

RULES:
- Do NOT create work cycles, tasks, or suggest phases during onboarding.
  Decomposition happens after onboarding is complete.
- Do NOT mention points, sprints, velocity, S/M/L/XL, or any internal system.
- One question per message. Wait for their reply before asking the next thing.
- If the user says something unexpected, respond to WHAT THEY SAID first,
  then guide back to what you still need.
"""

_CAPACITY_LANGUAGE_ADDENDUM = """
ESTIMATES — INTERNAL ONLY, NEVER SHOW TO USERS:
When creating tasks, pick an estimate internally: S, M, L, or XL.
NEVER say "S", "M", "L", "XL", "small", "medium", "large", "points", "pts", or "story points".
NEVER say "I'll mark that as M" or "That's an L task."
Always use time language:
S = "a few hours"
M = "a day or two"
L = "most of the week"
XL = "more than a week" (flag as risky, suggest breaking down)
Talk about capacity in days: "You usually get about 3 good days of work done per week."
When over-planned: "That's about 5 days of work for a 3-day week. What can wait?"
When calling create_task, pass the estimate parameter (S/M/L/XL) but say the time version to the user.
If a user asks "how long will that take", respond with time language. Never explain the sizing system.

GOAL DECOMPOSITION — during planning sessions and on-demand, never during initial onboarding.
When breaking down a goal for the first time:
1. Confirm you understand — restate it in one sentence.
2. If no deadline, suggest one together.
3. Propose 2-3 phases in one message. Keep it brief:
   "I'd break this into: research and pick a template, then write content,
   then launch. Sound right?"
4. Store confirmed phases in the project description.
5. Plan THIS WEEK only — propose 2-3 concrete tasks for the current phase.
6. Future phases stay in the plan. Don't create tasks for them.
Break this across multiple messages. One step, one reply, then the next.
Never propose phases AND weekly tasks in the same message.

NEW GOALS — capture vs plan:
When a user mentions a new goal after onboarding:
Save it immediately with create_project (name and deadline if mentioned).
Ask: "Want to break this down now, or should I bring it up on your next planning day?"
If they want to plan now, run the decomposition flow above.
If they want to wait, create the project with no cycle, no tasks, no phases.
Just the name and deadline. It shows up as backlog on planning day.

BACKLOG vs ACTIVE GOALS:
A goal WITH an active work cycle = active (being worked on this week).
A goal WITHOUT a work cycle = backlog (saved, waiting to be planned).
The pre-loaded context labels both clearly. Reference backlog goals on planning day.
Never create a work cycle for a backlog goal unless the user explicitly asks.

MULTIPLE ACTIVE GOALS:
Users can have multiple active goals. Each is a separate project.
When planning or checking in, reference all active goals.
If a user mentions a new goal mid-conversation, create a new project.
Don't merge it into an existing one unless they ask.

PLANNING DAY (Monday or user-configured):
Run this as a conversation, not a checklist.
1. Start with last week's results if available: "Last week you finished X of Y tasks."
2. For each active goal, ask what the focus is this week. One goal at a time.
3. After tasks are set for active goals, surface backlog goals that haven't been
   broken down yet: "You also have [X] saved but haven't planned it out yet.
   Want to break it down and start this week?"
   If they say yes, run the goal decomposition flow for that goal.
   If they say no, leave it in backlog.
4. If total workload exceeds their usual capacity, flag it:
   "That's about 5 days of work — you usually get about 3 done. What can wait?"
Create a new work cycle for each active goal as tasks are confirmed.
Don't pre-plan everything and dump it — let the user shape the week.

WHEN THE WEEK IS ALREADY PLANNED:
If a user already has tasks for the week and texts you, don't re-plan. Help them
with what they have — check in, update status, work through blockers.

HABITS — separate from goals. Use create_habit, not create_task.
Mention habits alongside tasks in morning check-ins.
Include habit streaks in Friday reviews.
Celebrate milestones. If a streak breaks, be encouraging — don't guilt.

FRIDAY REVIEWS — run as a conversation, not a report.
Start with the numbers: tasks done vs planned, name specific tasks.
Wait for their response.
Then share one observation — a pattern, a win, or something you noticed.
Wait for their response.
End with one concrete suggestion for next week.
Include habit streaks naturally. Don't dump everything at once.
If the user only has 1-2 weeks of data, keep the review light.
You don't have enough data for real patterns yet — say so honestly.
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
        for k, v in parse_qs(_get_body(event), keep_blank_values=True).items()
    }
    valid = validator.validate(url, params, signature)
    if not valid:
        logger.warning(
            "Twilio signature mismatch",
            has_signature=bool(signature),
            reconstructed_url=url,
            from_number=params.get("From", "missing"),
        )
    return valid


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


def _build_user_context(user_id: str, user: dict, is_new_user: bool,
                        latest_outbound: dict | None = None) -> str:
    """
    Pre-load all user context into a string for the system prompt.
    Constraint #20: the agent never fetches its own context.
    """
    tz = user.get("timezone", "America/New_York")
    tone = user.get("preferred_tone", "balanced")
    name = user.get("name", "")

    from datetime import date as _date
    today = _date.today().isoformat()

    lines = [
        f"\nToday's date: {today}",
        f"Current user_id: {user_id}",
        f"User's timezone: {tz}",
        f"Coaching tone: {tone}",
    ]
    if name:
        lines.append(f"User's name: {name}")

    # Timezone inference for new users — agent confirms rather than asks
    if is_new_user:
        inferred_tz = infer_timezone_from_phone(user_id)
        display = TZ_DISPLAY_NAMES.get(inferred_tz, "Eastern time")
        lines.append(f"Inferred timezone from area code: {inferred_tz} ({display})")

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

    # --- Session-aware context (proactive message reply detection) ---
    if latest_outbound and latest_outbound.get("message_type"):
        # Only inject if the outbound was recent (within 6 hours)
        try:
            sent_str = latest_outbound.get("sent_at", "")
            if sent_str:
                sent_at = datetime.fromisoformat(sent_str.rstrip("Z")).replace(tzinfo=_tz.utc)
                age_hours = (datetime.now(_tz.utc) - sent_at).total_seconds() / 3600
                if age_hours <= 6:
                    msg_type = latest_outbound["message_type"]
                    type_map = {
                        "morning_reminder": "a morning check-in message",
                        "evening_checkin": "an evening check-in message",
                        "monday_planning": "a Monday planning message",
                        "friday_review": "a Friday review message",
                        "midweek_adjust": "a midweek adjustment message",
                    }
                    desc = type_map.get(msg_type, "a proactive message")
                    lines.append(f"\nThe user is replying to {desc}. Respond accordingly.")
        except Exception:
            pass  # Don't let session detection break context building

    # --- Onboarding addendum ---
    if is_new_user:
        lines.append(_ONBOARDING_ADDENDUM)

    return "\n".join(lines)


def _call_agent(user_id: str, message: str, is_new_user: bool, user: dict,
                latest_outbound: dict | None = None) -> str:
    """Run the Stride agent for an SMS message. Returns the reply string."""
    planning_day = int(user.get("planning_day", 1))
    tz = user.get("timezone", "America/New_York")

    # P0: Pre-load all user context (constraint #20)
    dynamic_suffix = _build_user_context(user_id, user, is_new_user, latest_outbound)

    history = get_conversation(user_id)

    # P1: Prompt caching — static prefix is cached (90% cheaper), dynamic suffix is not
    model = _CachedAnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
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
        cache_read = model.cache_read_tokens
        cache_write = model.cache_write_tokens

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
    _request_start = time.time()

    # 1. Twilio signature validation
    if not _validate_twilio(event):
        logger.warning("Invalid Twilio signature")
        return Response(status_code=403, content_type="text/plain", body="Forbidden")

    # 2. Parse fields
    body    = parse_qs(_get_body(event))
    user_id = body.get("From", ["unknown"])[0]
    message = body.get("Body", [""])[0].strip()

    logger.info("SMS received", user_id=user_id, message_length=len(message))

    # 3. Message validation
    msg_check = check_message(message)
    if msg_check is not None:
        logger.info("Message blocked", user_id=user_id, reason=msg_check, message_length=len(message))
        log_blocked_attempt(user_id, msg_check, message)
        if msg_check == "too_long":
            return _twiml(_TOO_LONG_REPLY)
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
        notify_phone = os.environ.get("NOTIFY_PHONE", "")
        if notify_phone:
            send_sms(notify_phone, f"Stride user unsubscribed: {user_id}")
        return _twiml(_UNSUBSCRIBED)

    # 6. Consent check
    consent = get_consent(user_id)
    consent_active = consent is not None and consent.get("status") == "active"

    if not consent_active:
        if msg_upper in ("YES", "START"):
            is_resubscribe = consent is not None
            record_consent(user_id=user_id, phone=user_id)
            logger.info("User opted in", user_id=user_id, keyword=msg_upper,
                         resubscribe=is_resubscribe)
            notify_phone = os.environ.get("NOTIFY_PHONE", "")
            if notify_phone and user_id != notify_phone:
                label = "re-subscribed" if is_resubscribe else "signed up"
                send_sms(notify_phone, f"Stride user {label}: {user_id}")

            if is_resubscribe:
                return _twiml(_WELCOME_BACK)

            # New user: agent owns the first message via REST, empty TwiML
            try:
                user = get_or_create_user(user_id=user_id, phone=user_id)
                if "error" not in user:
                    reply = _call_agent(
                        user_id=user_id,
                        message="[USER_OPTED_IN]",
                        is_new_user=True,
                        user=user,
                    )
                    send_sms(user_id, reply)
                    logger.info("Onboarding agent fired", user_id=user_id)
                else:
                    send_sms(user_id, _WELCOME)
            except Exception:
                logger.exception("Onboarding agent call failed", user_id=user_id)
                send_sms(user_id, _WELCOME)

            return Response(status_code=200, content_type="text/xml", body="<Response/>")
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

    # 8. Track replied_at on latest outbound (for tone derivation + session context)
    latest_out = None
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
    # Twilio hard-caps webhook responses at 15s. If the agent takes longer,
    # Twilio drops the TwiML and the user gets silence. To handle this:
    #   - Lambda timeout is 30s (gives the agent room to finish)
    #   - If agent finishes in <12s → return TwiML (free, synchronous)
    #   - If agent finishes in >=12s → Twilio likely timed out, send via REST API
    TWIML_DEADLINE = 12  # seconds — leave 3s buffer for Twilio's 15s limit
    try:
        reply = _call_agent(user_id=user_id, message=message, is_new_user=is_new_user,
                            user=user, latest_outbound=latest_out)
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

        elapsed = time.time() - _request_start
        if elapsed >= TWIML_DEADLINE:
            # Twilio likely already timed out — send reply via REST API
            logger.info("Async fallback", user_id=user_id, elapsed_s=round(elapsed, 1))
            send_sms(user_id, reply)
            return Response(status_code=200, content_type="text/xml", body="<Response/>")
        return _twiml(reply)
    except Exception:
        logger.exception("SMS agent call failed", user_id=user_id)
        elapsed = time.time() - _request_start
        if elapsed >= TWIML_DEADLINE:
            send_sms(user_id, _ERROR_REPLY)
            return Response(status_code=200, content_type="text/xml", body="<Response/>")
        return _twiml(_ERROR_REPLY)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)

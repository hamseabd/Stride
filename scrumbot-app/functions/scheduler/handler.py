"""
stride-scheduler — proactive outbound SMS Lambda.

Trigger: EventBridge rule (every 15 minutes).
No API Gateway route. No inbound user traffic.

Logic:
  1. Query GSI for users with active proactive consent
  2. For each user: timezone math → determine message type → dedup → send → log
"""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from shared.db import (
    get_consented_users,
    get_or_create_user,
    get_todays_outbound,
    get_outbound_since,
    log_outbound,
    update_preferred_tone,
)
from shared.sms import send_sms
from shared.tools import list_active_projects, get_cycle_data

logger = Logger()
tracer = Tracer()

# Opt-out footer appended to every outbound message
_OPT_OUT_FOOTER = "\n\nReply NO REMINDERS to stop"

# Estimate labels: internal → user-facing
ESTIMATE_LABELS = {
    "S": "a few hours",
    "M": "a day or two",
    "L": "most of the week",
    "XL": "more than a week",
}


def _get_user_local_time(user: dict) -> datetime:
    """Get current time in the user's timezone."""
    tz_str = user.get("timezone", "America/New_York")
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("America/New_York")
    return datetime.now(tz)


def _in_window(now_local: datetime, target_time: str, window_minutes: int = 15) -> bool:
    """Check if now_local is within window_minutes of target_time (HH:MM)."""
    try:
        hour, minute = map(int, target_time.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 9, 0
    target_min = hour * 60 + minute
    now_min = now_local.hour * 60 + now_local.minute
    return 0 <= (now_min - target_min) < window_minutes


def _determine_message_type(now_local: datetime, user: dict) -> str | None:
    """
    Determine which proactive message type (if any) should fire right now.

    Returns one of:
      monday_planning, morning_reminder, evening_checkin,
      midweek_adjust, friday_review, None
    """
    weekday = now_local.isoweekday()  # 1=Monday, 7=Sunday
    checkin_time = user.get("checkin_time", "09:00")
    evening_time = user.get("evening_time", "18:00")

    # Monday AM — planning
    if weekday == 1 and _in_window(now_local, checkin_time):
        return "monday_planning"

    # Friday PM — review
    if weekday == 5 and _in_window(now_local, evening_time):
        return "friday_review"

    # Wednesday PM — midweek adjust (before generic evening)
    if weekday == 3 and _in_window(now_local, evening_time):
        return "midweek_adjust"

    # Tue-Thu AM — morning reminder
    if weekday in (2, 3, 4) and _in_window(now_local, checkin_time):
        return "morning_reminder"

    # Tue-Thu PM — evening checkin
    if weekday in (2, 3, 4) and _in_window(now_local, evening_time):
        return "evening_checkin"

    return None


def _is_already_sent(user_id: str, date_str: str, message_type: str) -> bool:
    """Check if a message of this type was already sent today (dedup)."""
    todays = get_todays_outbound(user_id, date_str)
    return any(item.get("message_type") == message_type for item in todays)


MAX_TASKS_IN_REMINDER = 5


def _build_morning_reminder(user_id: str) -> str:
    """Build morning reminder from live DynamoDB data. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Morning! What are you working on today?"

    lines = []
    task_count = 0
    total_active = 0

    for project in projects["projects"]:
        cycle = project.get("active_cycle")
        if not cycle:
            continue
        cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
        if "error" in cycle_data:
            continue

        project_tasks = []
        for task in cycle_data.get("tasks", []):
            if task.get("status") in ("todo", "in_progress"):
                total_active += 1
                if task_count < MAX_TASKS_IN_REMINDER:
                    label = ESTIMATE_LABELS.get(task.get("estimate_label", ""), "")
                    estimate_str = f" ({label})" if label else ""
                    project_tasks.append(f"- {task.get('title', '?')}{estimate_str}")
                    task_count += 1

        if project_tasks:
            lines.append(f"{project['name']}:")
            lines.extend(project_tasks)

    if task_count == 0:
        return "Morning! No tasks set for this week yet. Want to plan some?"

    if total_active > MAX_TASKS_IN_REMINDER:
        lines.append(f"...and {total_active - MAX_TASKS_IN_REMINDER} more")

    lines.append("\nWhat are you tackling first?")
    return "Morning! Here's your plan:\n" + "\n".join(lines)


def _build_evening_checkin() -> str:
    """Static evening check-in prompt. No Claude call."""
    return "How'd today go? What did you get done?"


def _build_midweek_adjust(user_id: str) -> str:
    """Midweek adjustment prompt with progress data. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Midweek \u2014 how's the week going? Want to adjust anything?"

    done_count = 0
    total_count = 0

    for project in projects["projects"]:
        cycle = project.get("active_cycle")
        if not cycle:
            continue
        cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
        if "error" in cycle_data:
            continue
        for task in cycle_data.get("tasks", []):
            total_count += 1
            if task.get("status") == "done":
                done_count += 1

    if total_count == 0:
        return "Midweek \u2014 how's the week going? Want to adjust anything?"

    return (
        f"Midweek \u2014 {done_count} of {total_count} tasks done so far. "
        "On track, or want to adjust?"
    )


def _build_planning_prompt(user_id: str) -> str:
    """Build context for Monday planning with last week's results + backlog. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "New week! What are you focusing on?"

    # Split active vs backlog
    done_count = 0
    total_count = 0
    active_lines = []
    backlog_lines = []

    for p in projects["projects"]:
        due = f" (due {p['target_date']})" if p.get("target_date") else ""
        cycle = p.get("active_cycle")
        if cycle:
            active_lines.append(f"- {p['name']}{due}")
            cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
            if "error" not in cycle_data:
                for task in cycle_data.get("tasks", []):
                    total_count += 1
                    if task.get("status") == "done":
                        done_count += 1
        else:
            backlog_lines.append(p["name"])

    # Build header with last week's results
    if total_count > 0:
        header = f"New week! Last week you finished {done_count} of {total_count} tasks."
    else:
        header = "New week!"

    parts = [header]

    if active_lines:
        parts.append("Your goals:\n" + "\n".join(active_lines))

    # Surface backlog goals on planning day
    if backlog_lines:
        if len(backlog_lines) == 1:
            parts.append(f"You also have '{backlog_lines[0]}' saved \u2014 want to plan that too?")
        else:
            names = ", ".join(f"'{n}'" for n in backlog_lines)
            parts.append(f"You also have {names} saved \u2014 want to activate any of those?")

    parts.append("What's the focus this week?")
    return "\n".join(parts)


def _build_review_prompt(user_id: str) -> str:
    """Build context for Friday review. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Week's done \u2014 how did it go?"

    done_count = 0
    total_count = 0

    for project in projects["projects"]:
        cycle = project.get("active_cycle")
        if not cycle:
            continue
        cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
        if "error" in cycle_data:
            continue
        for task in cycle_data.get("tasks", []):
            total_count += 1
            if task.get("status") == "done":
                done_count += 1

    return (
        f"Week's done \u2014 you finished {done_count} of {total_count} tasks. "
        "How do you feel about this week?"
    )


def _derive_tone(user_id: str, now_local: datetime) -> None:
    """
    Bi-weekly tone derivation heuristic. Runs on Friday review weeks.
    Analyzes outbound reply patterns to update preferred_tone.
    """
    # Only run every other Friday (weeks where ISO week number is even)
    if now_local.isocalendar()[1] % 2 != 0:
        return

    since = (now_local - timedelta(days=14)).strftime("%Y-%m-%d")
    records = get_outbound_since(user_id, since)
    if not records:
        return

    replied = [r for r in records if r.get("replied_at")]
    reply_rate = len(replied) / len(records) if records else 0

    # Calculate average reply latency in minutes
    latencies = []
    for r in replied:
        try:
            sent = datetime.fromisoformat(r["sent_at"].rstrip("Z"))
            repl = datetime.fromisoformat(r["replied_at"].rstrip("Z"))
            latencies.append((repl - sent).total_seconds() / 60)
        except (KeyError, ValueError):
            continue

    avg_latency = sum(latencies) / len(latencies) if latencies else float("inf")

    # Heuristic
    if avg_latency < 30 and reply_rate > 0.6:
        tone = "direct"
    elif avg_latency > 120 or reply_rate < 0.3:
        tone = "encouraging"
    else:
        tone = "balanced"

    update_preferred_tone(user_id, tone)
    logger.info("Tone derived", user_id=user_id, tone=tone,
                avg_latency_min=round(avg_latency, 1), reply_rate=round(reply_rate, 2))


def _process_user(user_id: str) -> bool:
    """Process a single user: determine message type, dedup, send.

    Returns True only when a message was actually sent.
    """
    user = get_or_create_user(user_id=user_id, phone=user_id)
    if "error" in user:
        logger.error("Failed to get user", user_id=user_id)
        return False

    if not user.get("onboarded", False):
        logger.info("Skipping: not onboarded", user_id=user_id)
        return False

    now_local = _get_user_local_time(user)
    date_str = now_local.strftime("%Y-%m-%d")
    logger.info("Processing user",
                user_id=user_id,
                local_time=now_local.strftime("%H:%M"),
                weekday=now_local.isoweekday(),
                timezone=user.get("timezone", "?"))

    message_type = _determine_message_type(now_local, user)
    if not message_type:
        logger.info("No message type for current window", user_id=user_id)
        return False

    if _is_already_sent(user_id, date_str, message_type):
        logger.info("Dedup: already sent", user_id=user_id, message_type=message_type)
        return False

    # Build message based on type
    if message_type == "morning_reminder":
        body = _build_morning_reminder(user_id)
    elif message_type == "evening_checkin":
        body = _build_evening_checkin()
    elif message_type == "midweek_adjust":
        body = _build_midweek_adjust(user_id)
    elif message_type == "monday_planning":
        body = _build_planning_prompt(user_id)
    elif message_type == "friday_review":
        body = _build_review_prompt(user_id)
        _derive_tone(user_id, now_local)
    else:
        return False

    # Append opt-out footer
    body += _OPT_OUT_FOOTER

    # Send and log (pass local_date for timezone-correct dedup)
    if send_sms(to=user_id, body=body):
        log_outbound(user_id, body, message_type, local_date=date_str)
        logger.info("Proactive message sent", user_id=user_id, message_type=message_type)
        return True
    else:
        logger.error("Failed to send proactive message", user_id=user_id, message_type=message_type)
        return False


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    """EventBridge entry point — process all consented users."""
    t0 = time.monotonic()
    user_ids = get_consented_users()
    logger.info("Scheduler run", consented_users=len(user_ids))

    sent_count = 0
    error_count = 0
    for user_id in user_ids:
        try:
            if _process_user(user_id):
                sent_count += 1
        except Exception:
            logger.exception("Error processing user", user_id=user_id)
            error_count += 1

    run_duration_ms = round((time.monotonic() - t0) * 1000)
    logger.info("scheduler_metrics",
                users_processed=len(user_ids),
                sent_count=sent_count,
                error_count=error_count,
                run_duration_ms=run_duration_ms)

    return {"statusCode": 200, "processed": len(user_ids)}

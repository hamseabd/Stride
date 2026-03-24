"""
stride-scheduler — proactive outbound SMS Lambda.

Trigger: EventBridge rule (every 15 minutes).
No API Gateway route. No inbound user traffic.

Logic:
  1. Query GSI for users with active proactive consent
  2. For each user: timezone math → determine message type → dedup → send → log
"""

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


def _build_morning_reminder(user_id: str) -> str:
    """Build morning reminder from live DynamoDB data. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Good morning! What are you working on today?"

    lines = ["Good morning! Today you planned:"]
    task_count = 0

    for project in projects["projects"]:
        cycle = project.get("active_cycle")
        if not cycle:
            continue
        cycle_data = get_cycle_data(cycle_id=cycle["cycle_id"])
        if "error" in cycle_data:
            continue
        for task in cycle_data.get("tasks", []):
            if task.get("status") in ("todo", "in_progress"):
                label = ESTIMATE_LABELS.get(task.get("estimate_label", ""), "")
                estimate_str = f" ({label})" if label else ""
                lines.append(f"- {task.get('title', '?')}{estimate_str} - {project['name']}")
                task_count += 1

    if task_count == 0:
        return "Good morning! No tasks planned yet. Want to set some up?"

    lines.append("Reply when you get started!")
    return "\n".join(lines)


def _build_evening_checkin() -> str:
    """Static evening check-in prompt. No Claude call."""
    return "How'd today go? Quick check-in: what did you get done?"


def _build_midweek_adjust(user_id: str) -> str:
    """Midweek adjustment prompt with progress data. No Claude call."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Mid-week check: how's the week going? Want to adjust your plan?"

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
        return "Mid-week check: how's the week going? Want to adjust your plan?"

    return (
        f"Mid-week check: you've finished {done_count} of {total_count} tasks so far. "
        "On track, or want to adjust your plan?"
    )


def _build_nudge() -> str:
    """Static nudge for inactive users. No Claude call."""
    return "Haven't heard from you in a while \u2014 everything ok? Text me when you're ready to pick back up."


def _build_planning_prompt(user_id: str) -> str:
    """Build context for Monday planning. Claude will generate the actual message."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "New week! What are you focusing on?"

    project_summaries = []
    for p in projects["projects"]:
        project_summaries.append(f"- {p['name']}" + (f" (due {p['target_date']})" if p.get("target_date") else ""))

    return (
        "New week! Here are your active projects:\n"
        + "\n".join(project_summaries)
        + "\nWhat are you focusing on this week?"
    )


def _build_review_prompt(user_id: str) -> str:
    """Build context for Friday review. Claude will generate the actual message."""
    projects = list_active_projects(user_id=user_id)
    if "error" in projects or not projects.get("projects"):
        return "Week's wrapping up. How did it go?"

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
        f"Week's wrapping up. You finished {done_count} of {total_count} tasks. "
        "What went well? What would you do differently?"
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


def _process_user(user_id: str) -> None:
    """Process a single user: determine message type, dedup, send."""
    user = get_or_create_user(user_id=user_id, phone=user_id)
    if "error" in user:
        logger.error("Failed to get user", user_id=user_id)
        return

    if not user.get("onboarded", False):
        return

    now_local = _get_user_local_time(user)
    date_str = now_local.strftime("%Y-%m-%d")

    message_type = _determine_message_type(now_local, user)
    if not message_type:
        return

    if _is_already_sent(user_id, date_str, message_type):
        logger.info("Dedup: already sent", user_id=user_id, message_type=message_type)
        return

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
        return

    # Append opt-out footer
    body += _OPT_OUT_FOOTER

    # Send and log
    if send_sms(to=user_id, body=body):
        log_outbound(user_id, body, message_type)
        logger.info("Proactive message sent", user_id=user_id, message_type=message_type)
    else:
        logger.error("Failed to send proactive message", user_id=user_id, message_type=message_type)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    """EventBridge entry point — process all consented users."""
    user_ids = get_consented_users()
    logger.info("Scheduler run", consented_users=len(user_ids))

    for user_id in user_ids:
        try:
            _process_user(user_id)
        except Exception:
            logger.exception("Error processing user", user_id=user_id)

    return {"statusCode": 200, "processed": len(user_ids)}

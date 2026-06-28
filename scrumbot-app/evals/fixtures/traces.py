"""Fixture trace cases for L1 and L2 evals. No real user data — all IDs are fake."""
from dataclasses import dataclass, field
from datetime import date, timedelta

TOOL_REQUIRED_ARGS: dict[str, set[str]] = {
    "resolve_date": {"expression"},
    "create_project": {"user_id", "name"},
    "update_project": {"project_id"},
    "archive_project": {"project_id"},
    "create_work_cycle": {"project_id", "name", "start_date", "end_date"},
    "list_active_projects": set(),
    "create_task": {"title", "cycle_id"},
    "update_task_status": {"task_id", "status"},
    "get_cycle_data": {"cycle_id"},
    "create_checkin": {"user_id", "did", "doing"},
    "flag_blocker": {"task_id", "description"},
    "get_pace_history": {"project_id"},
    "get_user_patterns": {"user_id"},
    "record_velocity": {"cycle_id", "project_id", "planned_points", "delivered_points", "cycle_name"},
    "update_user_patterns": {"user_id", "delivered_points", "planned_points", "new_blockers"},
    "complete_onboarding": {"user_id"},
    "set_user_preference": {"user_id", "preference", "value"},
    "create_habit": {"user_id", "title"},
    "complete_habit": {"user_id", "habit_id"},
    "list_habits": {"user_id"},
    "submit_feedback": {"user_id", "feedback"},
}


@dataclass
class Trace:
    input: str
    response: str
    tool_calls: list[dict] = field(default_factory=list)
    context: str = ""
    preferred_tone: str = "balanced"


# Seeded IDs — these "exist" in fixture state for L1.7 hallucination checks
SEEDED_PROJECT_ID = "proj-11111111-1111-1111-1111-111111111111"
SEEDED_CYCLE_ID = "cycle-22222222-2222-2222-2222-222222222222"
SEEDED_TASK_ID = "task-33333333-3333-3333-3333-333333333333"
HALLUCINATED_TASK_ID = "task-99999999-9999-9999-9999-999999999999"

# L1.1 — Length (≤480 chars)
LONG_RESPONSE = Trace(
    input="What should I work on this week?",
    response="x" * 481,
)
VALID_RESPONSE = Trace(
    input="What should I work on this week?",
    response="Focus on the three tasks you committed to. Which one feels most urgent right now?",
)

# L1.2 — Jargon ban
JARGON_RESPONSE = Trace(
    input="How do I plan my week?",
    response="Let's kick off your sprint planning and create some story points for the standup.",
)

# L1.3 — XL size label leak
XL_LABEL_RESPONSE = Trace(
    input="How big is this task?",
    response="That task is XL — it will take most of the week.",
)

# L1.4 — Multiple questions (>1 question mark)
MULTI_QUESTION_RESPONSE = Trace(
    input="I finished the API. What now?",
    response="Great work! What's the next task? How much time do you have today?",
)

# L1.5 — Empty / whitespace-only response
EMPTY_RESPONSE = Trace(input="Hi", response="")
WHITESPACE_RESPONSE = Trace(input="Hi", response="   \n  ")

# L1.6 — Tool required args
VALID_TOOL_CALL = {"name": "create_task", "input": {"title": "Write tests", "cycle_id": "cycle-abc"}}
MISSING_ARG_TOOL_CALL = {"name": "create_task", "input": {"title": "Write tests"}}  # missing cycle_id
UNKNOWN_TOOL_CALL = {"name": "nonexistent_tool", "input": {}}

# L1.8 — PII in response
PII_EMAIL_RESPONSE = Trace(
    input="What is your email?",
    response="You can reach support at user@example.com for help.",
)
PII_PHONE_RESPONSE = Trace(
    input="What is the support number?",
    response="Call 555-867-5309 to reach us.",
)
CLEAN_RESPONSE = Trace(
    input="What should I do today?",
    response="Work on your highest-priority task. You committed to finishing the API integration today.",
)

# L1.9 — Onboarding state machine: complete_onboarding must follow project+cycle+task
GOOD_ONBOARDING_TOOL_CALLS = [
    {"name": "create_project", "input": {"user_id": "u1", "name": "My App"}},
    {"name": "create_work_cycle", "input": {
        "project_id": SEEDED_PROJECT_ID, "name": "Week 1",
        "start_date": "2026-06-01", "end_date": "2026-06-07",
    }},
    {"name": "create_task", "input": {"title": "Set up repo", "cycle_id": SEEDED_CYCLE_ID}},
    {"name": "complete_onboarding", "input": {"user_id": "u1"}},
]
BAD_ONBOARDING_EARLY = [
    {"name": "complete_onboarding", "input": {"user_id": "u1"}},
]
BAD_ONBOARDING_MISSING_TASK = [
    {"name": "create_project", "input": {"user_id": "u1", "name": "My App"}},
    {"name": "create_work_cycle", "input": {
        "project_id": SEEDED_PROJECT_ID, "name": "Week 1",
        "start_date": "2026-06-01", "end_date": "2026-06-07",
    }},
    {"name": "complete_onboarding", "input": {"user_id": "u1"}},
]

# L1.10 — Tool call budget (≤6 per turn)
WITHIN_BUDGET_CALLS = [{"name": "list_active_projects", "input": {}}] * 5
OVER_BUDGET_CALLS = [{"name": "list_active_projects", "input": {}}] * 7

# L1.11 — Date fields: valid ISO + not in the past
# Dates are computed relative to today so this fixture never rots (was hardcoded 2026-06-01).
_VALID_START = (date.today() + timedelta(days=7)).isoformat()
_VALID_END = (date.today() + timedelta(days=14)).isoformat()
VALID_DATE_CALL = {"name": "create_work_cycle", "input": {
    "project_id": SEEDED_PROJECT_ID, "name": "Week 1",
    "start_date": _VALID_START, "end_date": _VALID_END,
}}
PAST_DATE_CALL = {"name": "create_work_cycle", "input": {
    "project_id": SEEDED_PROJECT_ID, "name": "Old Week",
    "start_date": "2020-01-01", "end_date": "2020-01-07",
}}
INVALID_DATE_CALL = {"name": "create_work_cycle", "input": {
    "project_id": SEEDED_PROJECT_ID, "name": "Bad Week",
    "start_date": "not-a-date", "end_date": "also-bad",
}}

# L1.12 — Classifier intent recall (40 labeled pairs, 8 per intent)
CLASSIFIER_PAIRS: list[tuple[str, str]] = [
    # feedback (8)
    ("This is really helpful, thanks!", "feedback"),
    ("I love how you keep track of everything", "feedback"),
    ("The reminders are too frequent", "feedback"),
    ("Can you change the way you ask questions?", "feedback"),
    ("I don't like this format", "feedback"),
    ("This isn't working for me", "feedback"),
    ("Great session today", "feedback"),
    ("You're being too pushy", "feedback"),
    # remind_me (8)
    ("Send me reminders", "remind_me"),
    ("Yes please remind me daily", "remind_me"),
    ("Start sending me check-ins", "remind_me"),
    ("I want daily nudges", "remind_me"),
    ("Turn on reminders", "remind_me"),
    ("Yes remind me", "remind_me"),
    ("Send me morning check-ins", "remind_me"),
    ("Enable check-ins please", "remind_me"),
    # no_reminders (8)
    ("Stop the reminders", "no_reminders"),
    ("No more check-ins please", "no_reminders"),
    ("Turn off notifications", "no_reminders"),
    ("Please stop texting me so much", "no_reminders"),
    ("Disable reminders", "no_reminders"),
    ("I don't want daily messages", "no_reminders"),
    ("Pause the reminders for now", "no_reminders"),
    ("Stop checking in with me", "no_reminders"),
    # help (8)
    ("How does this work?", "help"),
    ("What can you do?", "help"),
    ("What commands do you support?", "help"),
    ("I'm confused, what is this?", "help"),
    ("Explain how to use this", "help"),
    ("Help", "help"),
    ("What is Stride?", "help"),
    ("How do I get started?", "help"),
    # conversation (8)
    ("I finished the auth flow today", "conversation"),
    ("Blocked on the API integration, third-party is down", "conversation"),
    ("Working on tests", "conversation"),
    ("I'm going to focus on the frontend today", "conversation"),
    ("Done with the database migration", "conversation"),
    ("Just shipped v1", "conversation"),
    ("Nothing got done today, had meetings all day", "conversation"),
    ("Starting on the payments feature", "conversation"),
]

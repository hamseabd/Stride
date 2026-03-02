#!/usr/bin/env python3
"""
Stride SMS Simulator — interactive local testing.

Usage:
    cd scrumbot-app
    PYTHONPATH=. .venv/bin/python chat.py                 # default: +15551234567
    PYTHONPATH=. .venv/bin/python chat.py +15559876543    # custom number

Requires: make up (LocalStack must be running on localhost:4566)
"""
import os
import sys

os.environ.setdefault("DYNAMODB_TABLE_NAME", "stride-local")
os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "stride-chat")

from dotenv import load_dotenv
load_dotenv()

from shared.db import (
    get_or_create_user, record_consent, get_consent,
    revoke_consent, get_conversation, save_conversation,
)
from shared.tools import (
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
)
from shared.prompt import STRIDE_SYSTEM_PROMPT
from strands import Agent
from strands.models.anthropic import AnthropicModel

TOOLS = [
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
]

SMS_ADDENDUM = """
You are responding via SMS. Additional rules:
- Keep every reply under 300 characters when possible.
- Never use markdown, bullet points, or any formatting.
- Plain sentences only.
- Never expose internal IDs, error messages, or technical details.
"""

CAPACITY_ADDENDUM = """
CRITICAL — how you talk about workload:
- Never say "points", "pts", "story points", or any numbers-based estimate system.
- Translate estimates to time: S = "a few hours", M = "a day or two", L = "most of the week", XL = "more than a week — that's risky, let's break it down."
- Talk about capacity in days: "You get about 3 good days of work done per week" (not "15 points").
- The point system exists internally for tracking. Users must NEVER see it.

GOAL DECOMPOSITION — how goals work:
- Projects = Goals. Each project has a target_date.
- Work cycles = Milestones within a goal.
- Tasks = weekly work within a milestone.
- YOU lead the breakdown: suggest milestones, suggest weekly tasks. User confirms or adjusts.
- When creating a project, ALWAYS ask for a target date.

HABITS — separate from goals:
- Habits are recurring tasks the user wants to maintain.
- Use create_habit for recurring practices, NOT create_task.
- Habits have streaks. Celebrate streaks!
- If a habit streak breaks, be encouraging not guilt-tripping.
"""

ONBOARDING_ADDENDUM = """
This is a new user — they have no projects yet.
Start with setup: ask what they want to achieve (their goal).
Ask for a target date: "When do you want this done by?"
Create their first project with the target_date, suggest milestones,
create a first work cycle covering this week, and their initial tasks.
After creating at least one task, ask if they have any daily practices
they want to maintain (habits like writing, exercise, reading).
If yes, use create_habit. If no, that's fine.
Then call complete_onboarding to mark them as set up.
"""


def main():
    phone = sys.argv[1] if len(sys.argv) > 1 else "+15551234567"
    print(f"Stride SMS Simulator")
    print(f"User: {phone}")
    print(f"Type 'quit' to exit, 'reset' to clear conversation\n")

    consent = get_consent(phone)
    if not consent or consent.get("status") != "active":
        record_consent(user_id=phone, phone=phone)
        print("[system] Auto-granted SMS consent\n")

    user = get_or_create_user(user_id=phone, phone=phone)
    if "error" in user:
        print(f"[error] Failed to create user: {user['error']}")
        return

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not message:
            continue
        if message.lower() == "quit":
            print("Bye!")
            break
        if message.lower() == "reset":
            save_conversation(phone, [], planning_day=int(user.get("planning_day", 1)))
            print("[system] Conversation cleared\n")
            continue

        msg_upper = message.upper().strip()

        if msg_upper == "STOP":
            revoke_consent(phone)
            print("Stride: You've been unsubscribed. Text again to re-join.\n")
            continue
        if msg_upper == "HELP":
            print("Stride: Stride helps you plan your week, check in daily, and review progress.")
            print("        Just text naturally — e.g. 'plan my week' or 'check in'.")
            print("        STOP — unsubscribe\n")
            continue

        user = get_or_create_user(user_id=phone, phone=phone)
        is_new = not user.get("onboarded", False)
        if is_new:
            projects = list_active_projects(user_id=phone)
            if projects.get("projects"):
                is_new = False

        tone = user.get("preferred_tone", "balanced")
        tz = user.get("timezone", "America/New_York")
        planning_day = int(user.get("planning_day", 1))

        system = (
            STRIDE_SYSTEM_PROMPT.strip()
            + f"\n\nCurrent user_id: {phone}"
            + f"\nUser's timezone: {tz}"
            + f"\nThis user responds best to a {tone} coaching style."
            + CAPACITY_ADDENDUM
            + SMS_ADDENDUM
        )
        if is_new:
            system += ONBOARDING_ADDENDUM

        history = get_conversation(phone)
        model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
        agent = Agent(model=model, system_prompt=system, tools=TOOLS, messages=history)

        try:
            result = agent(message)
            reply = str(result)
        except Exception as e:
            reply = f"[error] Agent failed: {e}"

        save_conversation(phone, agent.messages, planning_day=planning_day, user_timezone=tz)

        print(f"Stride: {reply}\n")


if __name__ == "__main__":
    main()

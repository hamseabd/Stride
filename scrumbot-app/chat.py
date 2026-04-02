#!/usr/bin/env python3
"""
Stride SMS Simulator — interactive local testing.

Uses the SAME prompt logic as the production handler so what you test
locally matches what users experience in prod.

Usage:
    cd scrumbot-app
    PYTHONPATH=. .venv/bin/python chat.py                 # new user (default number)
    PYTHONPATH=. .venv/bin/python chat.py +15559876543    # custom number
    PYTHONPATH=. .venv/bin/python chat.py --reset          # reset default user and start fresh
    PYTHONPATH=. .venv/bin/python chat.py +1555 --reset    # reset specific user

Requires: make up (LocalStack must be running on localhost:4566)

Commands inside the chat:
    reset     — clear conversation history and start fresh
    wipe      — full reset: delete user, conversation, projects, habits (start from scratch)
    quit      — exit
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

import boto3
from boto3.dynamodb.conditions import Key

from shared.db import (
    get_or_create_user, record_consent, get_consent,
    revoke_consent, get_conversation, save_conversation,
    set_onboarded,
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
from shared.prompt import STRIDE_SYSTEM_PROMPT
from shared.timezone import infer_timezone_from_phone, TZ_DISPLAY_NAMES
from strands import Agent
from strands.models.anthropic import AnthropicModel

# Import the production prompt pieces so local matches prod exactly
from functions.sms.handler import (
    _SMS_SYSTEM_ADDENDUM,
    _ONBOARDING_ADDENDUM,
    _CAPACITY_LANGUAGE_ADDENDUM,
    _build_user_context,
    _STATIC_PREFIX,
    TOOLS,
)


def _get_table():
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    kwargs = {"endpoint_url": endpoint} if endpoint else {}
    return boto3.resource("dynamodb", region_name="us-east-1", **kwargs).Table(
        os.getenv("DYNAMODB_TABLE_NAME", "stride-local")
    )


def wipe_user(phone: str):
    """Delete ALL records for a user from DynamoDB — full clean slate."""
    table = _get_table()
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"USER#{phone}"))
    items = resp.get("Items", [])

    # Also clean up project-level items (cycles, velocity)
    project_ids = []
    for item in items:
        sk = item.get("sk", "")
        if sk.startswith("PROJECT#"):
            project_ids.append(sk.replace("PROJECT#", ""))

    for pid in project_ids:
        proj_resp = table.query(KeyConditionExpression=Key("pk").eq(f"PROJECT#{pid}"))
        for pi in proj_resp.get("Items", []):
            # Clean up cycle-level items (tasks)
            csk = pi.get("sk", "")
            if csk.startswith("CYCLE#"):
                cid = csk.replace("CYCLE#", "")
                cycle_resp = table.query(KeyConditionExpression=Key("pk").eq(f"CYCLE#{cid}"))
                for ci in cycle_resp.get("Items", []):
                    table.delete_item(Key={"pk": ci["pk"], "sk": ci["sk"]})
            table.delete_item(Key={"pk": pi["pk"], "sk": pi["sk"]})

    for item in items:
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    count = len(items) + sum(1 for _ in project_ids)
    return count


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    phone = args[0] if args else "+15551234567"
    do_reset = "--reset" in flags

    print(f"Stride SMS Simulator")
    print(f"User: {phone}")
    print(f"Commands: 'quit' to exit, 'reset' to clear conversation, 'wipe' for full reset\n")

    if do_reset:
        count = wipe_user(phone)
        print(f"[system] Wiped {count} records for {phone}\n")

    # Ensure consent
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
        if message.lower() == "wipe":
            count = wipe_user(phone)
            print(f"[system] Wiped {count} records for {phone}")
            # Re-create user and consent
            record_consent(user_id=phone, phone=phone)
            user = get_or_create_user(user_id=phone, phone=phone)
            print("[system] Fresh user created\n")
            continue

        msg_upper = message.upper().strip()

        if msg_upper == "STOP":
            revoke_consent(phone)
            print("Stride: You've been unsubscribed. Text START anytime to re-join.\n")
            continue

        # Re-fetch user state each turn (onboarding may have changed it)
        user = get_or_create_user(user_id=phone, phone=phone)
        is_new = not user.get("onboarded", False)
        if is_new:
            projects = list_active_projects(user_id=phone)
            if projects.get("projects"):
                is_new = False
                set_onboarded(phone)

        # Build system prompt — SAME as production handler
        dynamic_suffix = _build_user_context(phone, user, is_new)

        history = get_conversation(phone)
        model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
        model.update_config(params={
            "system": [
                {"type": "text", "text": _STATIC_PREFIX, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": dynamic_suffix},
            ]
        })
        agent = Agent(model=model, tools=TOOLS, messages=history)

        try:
            result = agent(message)
            reply = str(result)
        except Exception as e:
            reply = f"[error] Agent failed: {e}"

        tz = user.get("timezone", "America/New_York")
        planning_day = int(user.get("planning_day", 1))
        save_conversation(phone, agent.messages, planning_day=planning_day, user_timezone=tz)

        # Show reply with char count (helpful for SMS length tuning)
        print(f"Stride ({len(reply)} chars): {reply}\n")


if __name__ == "__main__":
    main()

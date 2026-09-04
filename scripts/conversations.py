#!/usr/bin/env python3
"""
Review beta user conversations from DynamoDB.

Usage:
  python scripts/conversations.py                       # all users, current conversation
  python scripts/conversations.py --user +15551234567   # single user
  python scripts/conversations.py --all-users           # list all users with stats
  python scripts/conversations.py --feedback             # show all feedback records

Requires: boto3
"""

import argparse
import json
import os
import sys
from datetime import datetime

import boto3

TABLE = os.getenv("DYNAMODB_TABLE_NAME", "stride-prod")
REGION = "us-east-1"


def get_table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def get_all_users(table):
    """Scan for all user metadata records."""
    resp = table.scan(
        FilterExpression="sk = :sk",
        ExpressionAttributeValues={":sk": "#METADATA"},
    )
    return sorted(resp.get("Items", []), key=lambda u: u.get("created_at", ""))


def get_conversation(table, user_id):
    """Load current conversation for a user."""
    resp = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"}
    )
    item = resp.get("Item")
    if not item:
        return [], 0
    messages = json.loads(item.get("messages", "[]"))
    turn_count = int(item.get("turn_count", 0))
    return messages, turn_count


def get_projects(table, user_id):
    """List projects for a user."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":sk": "PROJECT#"},
    )
    return resp.get("Items", [])


def get_blocked(table, user_id):
    """List blocked message attempts for a user."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":sk": "BLOCKED#"},
    )
    return resp.get("Items", [])


def get_feedback(table):
    """Scan for all feedback records."""
    resp = table.scan(
        FilterExpression="begins_with(sk, :sk)",
        ExpressionAttributeValues={":sk": "FEEDBACK#"},
    )
    return sorted(resp.get("Items", []), key=lambda f: f.get("created_at", ""))


def format_phone(phone):
    """Format E.164 to readable."""
    if len(phone) == 12 and phone.startswith("+1"):
        return f"({phone[2:5]}) {phone[5:8]}-{phone[8:]}"
    return phone


def print_user_summary(users, table):
    """Print a summary table of all users."""
    print(f"\n{'='*70}")
    print(f" STRIDE BETA USERS — {len(users)} total")
    print(f"{'='*70}\n")

    for u in users:
        uid = u.get("user_id", u.get("pk", "").replace("USER#", ""))
        name = u.get("name", "") or "(no name)"
        phone = format_phone(uid)
        tz = u.get("timezone", "?")
        onboarded = "Yes" if u.get("onboarded") else "No"
        created = u.get("created_at", "?")[:10]

        _, turn_count = get_conversation(table, uid)
        projects = get_projects(table, uid)

        print(f"  {name:<15} {phone:<16} tz={tz}")
        print(f"  {'':15} onboarded={onboarded}  turns={turn_count}  projects={len(projects)}  joined={created}")
        print()


def print_conversation(messages, user_id, name=""):
    """Pretty-print a conversation thread."""
    label = name or user_id
    print(f"\n{'='*70}")
    print(f" CONVERSATION: {label} ({format_phone(user_id)})")
    print(f"{'='*70}\n")

    if not messages:
        print("  (no conversation history)\n")
        return

    for msg in messages:
        role = msg.get("role", "?")
        content_parts = msg.get("content", [])

        # Skip tool result messages
        if role == "user" and any(isinstance(p, dict) and "toolResult" in p for p in content_parts):
            continue

        # Extract text from content parts
        texts = []
        tool_calls = []
        for part in content_parts:
            if isinstance(part, dict):
                if "text" in part:
                    texts.append(part["text"])
                elif "toolUse" in part:
                    tool_calls.append(part["toolUse"]["name"])
            elif isinstance(part, str):
                texts.append(part)

        if not texts and not tool_calls:
            continue

        if role == "user":
            prefix = f"  {label}:"
        else:
            prefix = "  Stride:"

        for text in texts:
            # Wrap long lines
            words = text.split()
            lines = []
            line = ""
            for w in words:
                if len(line) + len(w) + 1 > 65:
                    lines.append(line)
                    line = w
                else:
                    line = f"{line} {w}" if line else w
            if line:
                lines.append(line)

            print(f"{prefix} {lines[0]}")
            for extra in lines[1:]:
                print(f"  {'':>8} {extra}")

        if tool_calls:
            print(f"  {'':>8} [tools: {', '.join(tool_calls)}]")

        print()


def print_blocked(blocked_items, user_id):
    """Print blocked message attempts."""
    if not blocked_items:
        return

    print(f"  Blocked messages ({len(blocked_items)}):")
    for b in blocked_items:
        reason = b.get("reason", "?")
        at = b.get("created_at", "?")[:19]
        preview = b.get("message_preview", "(no preview)")
        # Show full message, wrapped
        lines = []
        words = preview.split()
        line = ""
        for w in words:
            if len(line) + len(w) + 1 > 60:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}" if line else w
        if line:
            lines.append(line)

        print(f"    [{at}] reason={reason}")
        for i, l in enumerate(lines):
            print(f"      {'>' if i == 0 else ' '} {l}")
    print()


def print_feedback(feedback_items):
    """Print all feedback records."""
    print(f"\n{'='*70}")
    print(f" FEEDBACK — {len(feedback_items)} records")
    print(f"{'='*70}\n")

    if not feedback_items:
        print("  (no feedback yet)\n")
        return

    for f in feedback_items:
        uid = f.get("pk", "").replace("USER#", "")
        body = f.get("body", "(empty)")
        source = f.get("source", "?")
        at = f.get("created_at", "?")[:19]
        print(f"  [{at}] {format_phone(uid)} ({source})")
        print(f"    {body}\n")


def main():
    parser = argparse.ArgumentParser(description="Review Stride beta conversations")
    parser.add_argument("--user", "-u", help="Show conversation for a specific user (E.164 phone)")
    parser.add_argument("--all-users", "-a", action="store_true", help="List all users with stats")
    parser.add_argument("--feedback", "-f", action="store_true", help="Show all feedback records")
    parser.add_argument("--table", "-t", default=TABLE, help=f"DynamoDB table (default: {TABLE})")
    args = parser.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(args.table)

    if args.feedback:
        print_feedback(get_feedback(table))
        return

    users = get_all_users(table)

    if args.all_users:
        print_user_summary(users, table)
        return

    if args.user:
        # Single user
        uid = args.user
        user = next((u for u in users if u.get("user_id") == uid), {})
        name = user.get("name", "") or ""
        messages, _ = get_conversation(table, uid)
        projects = get_projects(table, uid)
        blocked = get_blocked(table, uid)

        print_conversation(messages, uid, name)

        if projects:
            print(f"  Projects ({len(projects)}):")
            for p in projects:
                print(f"    - {p.get('name', '?')} (target: {p.get('target_date', '?')})")
                if p.get("description"):
                    print(f"      {p['description'][:80]}")
            print()

        print_blocked(blocked, uid)
        return

    # Default: show all conversations
    for u in users:
        uid = u.get("user_id", u.get("pk", "").replace("USER#", ""))
        name = u.get("name", "") or ""
        messages, _ = get_conversation(table, uid)
        print_conversation(messages, uid, name)


if __name__ == "__main__":
    main()

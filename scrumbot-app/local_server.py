#!/usr/bin/env python3
"""
Stride local server — Flask app that mirrors the production API.

Routes:
    POST /checkin    — record a daily check-in
    POST /ceremony   — run a Stride session (setup / planning / review / refinement)
    GET  /health     — confirm server is up

Usage:
    python local_server.py
    python local_server.py --port 8080

Test with curl:
    curl -s -X POST http://localhost:8000/checkin \
      -H "Content-Type: application/json" \
      -d '{"user_id":"u1","did":"wrote tests","doing":"deploy today","blocked":""}' | python -m json.tool

    curl -s -X POST http://localhost:8000/ceremony \
      -H "Content-Type: application/json" \
      -d '{"user_id":"u1","type":"setup","message":"help me get started","history":[]}' | python -m json.tool

    # Multi-turn: pass the history from the previous response back in:
    curl -s -X POST http://localhost:8000/ceremony \
      -H "Content-Type: application/json" \
      -d '{"user_id":"u1","type":"setup","message":"I am building a mobile app","history":[...]}' | python -m json.tool
"""
import os
import argparse
import json

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("DYNAMODB_TABLE_NAME",       "stride-local")
os.environ.setdefault("AWS_ENDPOINT_URL",          "http://localhost:4566")
os.environ.setdefault("AWS_ACCESS_KEY_ID",         "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY",     "test")
os.environ.setdefault("AWS_DEFAULT_REGION",        "us-east-1")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME",   "stride-local")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("LOG_LEVEL",                 "WARNING")

from flask import Flask, request, jsonify
from aws_lambda_powertools import Logger
from strands import Agent
from strands.models.anthropic import AnthropicModel

from shared.prompt import STRIDE_SYSTEM_PROMPT
from shared.guards import check_message
from shared.tools import (
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
)

TOOLS = [
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
]

MAX_HISTORY_TURNS = 20

app = Flask(__name__)
local_logger = Logger(service="stride-local")


def _build_agent(user_id: str, history: list) -> Agent:
    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=2048)
    system = STRIDE_SYSTEM_PROMPT.strip() + f"\n\nCurrent user_id: {user_id}"
    return Agent(
        model=model,
        system_prompt=system,
        tools=TOOLS,
        messages=history,
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "table": os.environ["DYNAMODB_TABLE_NAME"]})


@app.post("/checkin")
def checkin():
    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "")
    did     = body.get("did", "")
    doing   = body.get("doing", "")
    blocked = body.get("blocked", "")

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not did or not doing:
        return jsonify({"error": "did and doing are required"}), 400

    result = create_checkin(user_id=user_id, did=did, doing=doing, blocked=blocked)
    if "error" in result:
        return jsonify(result), 500

    return jsonify({
        "checkin_id": result["checkin_id"],
        "date":       result["date"],
        "message":    "Check-in recorded.",
    })


@app.post("/ceremony")
def ceremony():
    body     = request.get_json(force=True) or {}
    user_id  = body.get("user_id", "")
    message  = body.get("message", "")
    history  = body.get("history", [])

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    # Message validation
    msg_check = check_message(message)
    if msg_check is not None:
        return jsonify({"error": f"Message rejected: {msg_check}"}), 400

    # History cap — prevent unbounded token growth
    if len(history) > MAX_HISTORY_TURNS:
        local_logger.warning(
            "History truncated",
            original_len=len(history),
            cap=MAX_HISTORY_TURNS,
        )
        history = history[-MAX_HISTORY_TURNS:]

    try:
        agent    = _build_agent(user_id, history)
        response = agent(message)
        return jsonify({
            "reply":   str(response),
            "history": agent.messages,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/test-scheduler")
def test_scheduler():
    """
    GET /test-scheduler
    Dry-run the proactive message scheduler.

    Query params:
      send=true     — actually send via Twilio (requires creds, default: dry-run)
      user=+1...    — filter to one user (optional)

    In Phase 2 this is a scaffold. Full implementation ships in Phase 3 when
    proactive consent + outbound SMS exist.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from shared.db import get_table

    dry_run = request.args.get("send", "false").lower() != "true"
    filter_user = request.args.get("user", "")

    try:
        items = get_table().scan(
            FilterExpression="sk = :meta",
            ExpressionAttributeValues={":meta": "#METADATA"},
        ).get("Items", [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = []

    for item in items:
        pk = item.get("pk", "")
        if not pk.startswith("USER#"):
            continue
        user_id = pk.replace("USER#", "")
        if filter_user and user_id != filter_user:
            continue

        tz_str = item.get("timezone", "America/New_York")
        try:
            user_tz = ZoneInfo(tz_str)
        except Exception:
            user_tz = ZoneInfo("America/New_York")

        now_local = datetime.now(user_tz)
        weekday = now_local.isoweekday()   # 1=Mon, 5=Fri, 7=Sun
        hour    = now_local.hour
        checkin_hour = int(item.get("checkin_time", "09:00").split(":")[0])
        evening_hour = int(item.get("evening_time", "18:00").split(":")[0])

        message_type = None
        if weekday == 1 and hour == checkin_hour:
            message_type = "monday_planning"
        elif weekday == 5 and hour == evening_hour:
            message_type = "friday_review"
        elif 2 <= weekday <= 4 and hour == checkin_hour:
            message_type = "morning_reminder"
        elif 2 <= weekday <= 4 and hour == evening_hour:
            message_type = "evening_checkin"
        elif weekday == 3 and hour == 12:
            message_type = "midweek_adjust"

        results.append({
            "user_id": user_id,
            "timezone": tz_str,
            "local_time": now_local.strftime("%Y-%m-%d %H:%M %Z"),
            "message_type": message_type or "none",
            "would_send": message_type is not None,
            "dry_run": dry_run,
        })

    to_send = [r for r in results if r["would_send"]]

    return jsonify({
        "checked_users": len(results),
        "would_send_count": len(to_send),
        "dry_run": dry_run,
        "results": results,
    })


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": f"Route not found. Available: POST /checkin, POST /ceremony, GET /health, GET /test-scheduler"}), 404


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stride local server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"\n{'─'*50}")
    print(f"  Stride local server")
    print(f"  http://{args.host}:{args.port}")
    print(f"  table: {os.environ['DYNAMODB_TABLE_NAME']}")
    print(f"{'─'*50}\n")

    app.run(host=args.host, port=args.port, debug=False)

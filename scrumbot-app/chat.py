#!/usr/bin/env python3
"""
Stride SMS simulator — talk to the production agent from your terminal.

Runs the SAME system prompt, tools, context builder, intent classifier and
tenant binding as the stride-sms Lambda. DynamoDB is mocked in-process with
moto by default, so the only thing you need is an Anthropic key:

    cp .env.example .env          # set ANTHROPIC_API_KEY
    make chat                     # or: PYTHONPATH=. python chat.py

Usage:
    chat.py [PHONE] [--reset] [--localstack] [--script FILE] [--record FILE] [--trace FILE]

    PHONE          user id in E.164 (default +15551234567)
    --reset        wipe the user before starting
    --localstack   use LocalStack on localhost:4566 instead of moto
                   (requires `make up`; state then persists across runs)
    --script FILE  non-interactive: one user message per line; prints the
                   conversation and exits
    --record FILE  append one JSON line per turn (used to render docs/examples)
    --trace FILE   write every OpenTelemetry span from the session as JSON
                   (moto mode only)

In-chat commands: reset (clear history), wipe (delete everything), quit.
"""

import argparse
import json
import math
import os
import sys
import time

from dotenv import load_dotenv

os.environ.setdefault("DYNAMODB_TABLE_NAME", "stride-local")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "stride-chat")

import boto3
from boto3.dynamodb.conditions import Key
from strands import Agent

from shared.classifier import classify_intent
from shared.db import (
    get_or_create_user, record_consent, get_consent, revoke_consent,
    get_conversation, save_conversation, set_onboarded,
    record_proactive_consent, revoke_proactive_consent, store_feedback,
)
from shared.tenant import bind_user
from shared.tools import list_active_projects
from shared.validators import validate_response, MAX_SMS_CHARS
from functions.sms.handler import (
    _build_user_context, _STATIC_PREFIX, TOOLS, _CachedAnthropicModel,
)

DEFAULT_PHONE = "+15551234567"
SMS_SEGMENT = 160

# Canned replies mirror functions/sms/handler.py so a scripted session reads like prod.
_CANNED = {
    "feedback": "Thanks for the feedback — I'll pass it along to the team.",
    "remind_me": "You'll get daily check-ins! Reply NO REMINDERS to stop.",
    "no_reminders": "Got it — no more reminders. Text me anytime.",
}


# ── DynamoDB backend ─────────────────────────────────────────────────────────

def start_backend(localstack: bool):
    """Return a stop() callable. Moto runs in-process; LocalStack needs `make up`."""
    import shared.db as db_module
    db_module._table = None
    if localstack:
        os.environ["AWS_ENDPOINT_URL"] = "http://localhost:4566"
        return lambda: None
    os.environ.pop("AWS_ENDPOINT_URL", None)  # .env may point at LocalStack
    from moto import mock_aws
    from testsupport import create_stride_table
    mock = mock_aws()
    mock.start()
    create_stride_table(boto3.client("dynamodb", region_name="us-east-1"),
                        table_name=os.environ["DYNAMODB_TABLE_NAME"])
    return mock.stop


def _table():
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    kwargs = {"endpoint_url": endpoint} if endpoint else {}
    return boto3.resource("dynamodb", region_name="us-east-1", **kwargs).Table(
        os.environ["DYNAMODB_TABLE_NAME"])


def wipe_user(phone: str) -> int:
    """Delete every record under USER#phone and the projects it owns."""
    table = _table()
    count = 0
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"USER#{phone}"))
    for item in resp.get("Items", []):
        if item["sk"].startswith("PROJECT#"):
            pid = item["sk"].split("#", 1)[1]
            sub = table.query(KeyConditionExpression=Key("pk").eq(f"PROJECT#{pid}"))
            for s in sub.get("Items", []):
                table.delete_item(Key={"pk": s["pk"], "sk": s["sk"]})
                count += 1
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        count += 1
    return count


def ensure_user(phone: str) -> dict:
    consent = get_consent(phone)
    if not consent or consent.get("status") != "active":
        record_consent(user_id=phone, phone=phone)
    return get_or_create_user(user_id=phone, phone=phone)


# ── Telemetry capture (moto mode) ────────────────────────────────────────────

def start_trace_capture():
    """Install an in-memory span exporter as the global provider. Must run before
    any Agent is built, because Strands latches onto the first provider."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    import shared.telemetry as telemetry

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "stride-chat"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    telemetry._provider = provider
    telemetry._instrument_botocore()
    return exporter


def dump_spans(exporter, path: str) -> None:
    def _hex(v, width):
        return format(v, f"0{width}x")

    out = []
    for s in exporter.get_finished_spans():
        ctx = s.get_span_context()
        out.append({
            "name": s.name,
            "trace_id": _hex(ctx.trace_id, 32),
            "span_id": _hex(ctx.span_id, 16),
            "parent_id": _hex(s.parent.span_id, 16) if s.parent else None,
            "start_ns": s.start_time,
            "end_ns": s.end_time,
            "status": s.status.status_code.name,
            "attributes": {k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                           for k, v in dict(s.attributes or {}).items()},
        })
    with open(path, "w") as f:
        json.dump(out, f, indent=1)


# ── One turn ─────────────────────────────────────────────────────────────────

def extract_tool_calls(messages: list) -> list[dict]:
    """Tool calls the agent made, in order, with user_id stripped (it is bound server-side)."""
    calls = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for block in m.get("content", []):
            tu = block.get("toolUse")
            if tu:
                inp = {k: v for k, v in (tu.get("input") or {}).items() if k != "user_id"}
                calls.append({"name": tu["name"], "input": inp})
    return calls


def _segments(text: str) -> int:
    return max(1, math.ceil(len(text) / SMS_SEGMENT))


def run_turn(phone: str, message: str) -> dict:
    """Mirror of the handler's routing for one inbound SMS. Returns a record dict."""
    t0 = time.monotonic()
    intent = classify_intent(message)
    base = {"user": message, "intent": intent, "tools": [],
            "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
            "cost_usd": 0.0}

    if intent == "feedback":
        store_feedback(phone, message, source="classifier")
    elif intent == "remind_me":
        record_proactive_consent(phone)
    elif intent == "no_reminders":
        revoke_proactive_consent(phone)
    if intent in _CANNED:
        reply = _CANNED[intent]
        return {**base, "reply": reply, "chars": len(reply), "segments": _segments(reply),
                "latency_ms": round((time.monotonic() - t0) * 1000)}

    user = get_or_create_user(user_id=phone, phone=phone)
    is_new = not user.get("onboarded", False)
    if is_new and list_active_projects(user_id=phone).get("projects"):
        is_new = False
        set_onboarded(phone)

    history = get_conversation(phone)
    before = len(history)
    model = _CachedAnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
    model.update_config(params={"system": [
        {"type": "text", "text": _STATIC_PREFIX, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": _build_user_context(phone, user, is_new)},
    ]})
    agent = Agent(model=model, tools=TOOLS, messages=history)

    with bind_user(phone):
        result = agent(message)
    reply = str(result)

    save_conversation(phone, agent.messages, planning_day=int(user.get("planning_day", 1)),
                      user_timezone=user.get("timezone", "America/New_York"))
    warnings = validate_response(reply, user_id=phone)
    if warnings.get("length_exceeded"):
        reply = reply[:MAX_SMS_CHARS]

    usage = result.metrics.accumulated_usage
    inp, out = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
    cr, cw = model.cache_read_tokens, model.cache_write_tokens
    return {
        **base,
        "reply": reply, "chars": len(reply), "segments": _segments(reply),
        "tools": extract_tool_calls(agent.messages[before:]),
        "input_tokens": inp, "output_tokens": out, "cache_read": cr, "cache_write": cw,
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "cost_usd": round((inp * 3 + out * 15 + cr * 0.30 + cw * 3.75) / 1_000_000, 6),
    }


def _print_turn(rec: dict) -> None:
    print(f"Stride ({rec['chars']} chars, {rec['segments']} seg): {rec['reply']}")
    tools = ", ".join(f"{t['name']}({', '.join(f'{k}={v!r}' for k, v in t['input'].items())})"
                      for t in rec["tools"]) or "none"
    print(f"  [under the hood] intent={rec['intent']}  tools={tools}")
    print(f"  [tokens] in={rec['input_tokens']} out={rec['output_tokens']} "
          f"cache_read={rec['cache_read']} cache_write={rec['cache_write']}  "
          f"{rec['latency_ms']} ms  ${rec['cost_usd']:.4f}\n")


# ── Entry point ──────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    load_dotenv()

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("phone", nargs="?", default=DEFAULT_PHONE)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--localstack", action="store_true")
    p.add_argument("--script")
    p.add_argument("--record")
    p.add_argument("--trace")
    args = p.parse_args(argv)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 2
    if args.trace and args.localstack:
        print("--trace works in moto mode only.")
        return 2

    exporter = start_trace_capture() if args.trace else None
    stop = start_backend(args.localstack)
    record = open(args.record, "a") if args.record else None

    try:
        if args.reset and args.localstack:
            print(f"[system] wiped {wipe_user(args.phone)} records")
        user = ensure_user(args.phone)
        if "error" in user:
            print(f"[error] {user['error']}")
            return 1

        print(f"Stride SMS simulator — user {args.phone} — "
              f"{'LocalStack' if args.localstack else 'moto (in-process)'}\n")

        def turn(message: str):
            rec = run_turn(args.phone, message)
            _print_turn(rec)
            if record:
                record.write(json.dumps(rec) + "\n")
                record.flush()

        if not user.get("onboarded", False) and not get_conversation(args.phone):
            # Production: the agent owns the first message after opt-in.
            print("You: START\n[system] opt-in recorded; the agent sends the opener\n")
            turn("[USER_OPTED_IN]")

        if args.script:
            with open(args.script) as f:
                for line in f:
                    message = line.strip()
                    if not message or message.startswith("#"):
                        continue
                    print(f"You: {message}")
                    turn(message)
            return 0

        while True:
            try:
                message = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                return 0
            if not message:
                continue
            low = message.lower()
            if low == "quit":
                return 0
            if low == "reset":
                save_conversation(args.phone, [], planning_day=int(user.get("planning_day", 1)))
                print("[system] conversation cleared\n")
                continue
            if low == "wipe":
                print(f"[system] wiped {wipe_user(args.phone)} records")
                user = ensure_user(args.phone)
                continue
            if message.upper() == "STOP":
                revoke_consent(args.phone)
                print("Stride: You've been unsubscribed. Text START anytime to re-join.\n")
                continue
            turn(message)
    finally:
        if record:
            record.close()
        if exporter:
            import shared.telemetry as telemetry
            telemetry.flush()
            dump_spans(exporter, args.trace)
            print(f"[system] wrote {len(exporter.get_finished_spans())} spans to {args.trace}")
        stop()


if __name__ == "__main__":
    sys.exit(main())

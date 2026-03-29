#!/usr/bin/env python3
"""
Stride production analytics — query CloudWatch Logs for agent/classifier/scheduler metrics.

Usage:
  python scripts/analyze.py                  # last 24h summary
  python scripts/analyze.py --hours 168      # last 7 days
  python scripts/analyze.py --cost           # cost breakdown only
  python scripts/analyze.py --quality        # response quality checks
  python scripts/analyze.py --classifier     # classifier intent breakdown
  python scripts/analyze.py --scheduler      # scheduler run stats
  python scripts/analyze.py --all            # everything
  python scripts/analyze.py --export csv     # export raw data to CSV

Requires: boto3, tabulate (pip install tabulate)
AWS credentials must be configured (same profile as your Lambda).
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import boto3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SMS_LOG_GROUP = "/aws/lambda/stride-sms"
SCHEDULER_LOG_GROUP = "/aws/lambda/stride-scheduler"
REGION = "us-east-1"

# Sonnet: $3/$15 per MTok | Haiku: $1/$5 per MTok
PRICING = {
    "sonnet_input": 3.0 / 1_000_000,
    "sonnet_output": 15.0 / 1_000_000,
    "sonnet_cache_read": 0.3 / 1_000_000,
    "sonnet_cache_write": 3.75 / 1_000_000,
    "haiku_input": 1.0 / 1_000_000,
    "haiku_output": 5.0 / 1_000_000,
}

client = boto3.client("logs", region_name=REGION)


# ---------------------------------------------------------------------------
# CloudWatch Logs Insights queries
# ---------------------------------------------------------------------------
def _run_query(log_group: str, query: str, hours: int) -> list[dict]:
    """Run a CloudWatch Logs Insights query and return results."""
    end = int(time.time())
    start = end - (hours * 3600)

    resp = client.start_query(
        logGroupName=log_group,
        startTime=start,
        endTime=end,
        queryString=query,
        limit=10000,
    )
    query_id = resp["queryId"]

    # Poll until complete
    while True:
        result = client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)

    if result["status"] != "Complete":
        print(f"  Query {result['status']}: {query[:80]}...")
        return []

    rows = []
    for r in result.get("results", []):
        row = {field["field"]: field["value"] for field in r}
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------
def agent_summary(hours: int) -> None:
    """Summarize agent call metrics from structured logs."""
    query = """
    filter message = "agent_metrics"
    | stats
        count(*) as calls,
        avg(input_tokens) as avg_input,
        avg(output_tokens) as avg_output,
        avg(cache_read_tokens) as avg_cache_read,
        avg(agent_latency_ms) as avg_latency_ms,
        max(agent_latency_ms) as max_latency_ms,
        avg(estimated_cost_usd) as avg_cost,
        sum(estimated_cost_usd) as total_cost,
        avg(reply_length) as avg_reply_len,
        max(reply_length) as max_reply_len
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        print("  No agent calls found.")
        return

    r = rows[0]
    print(f"  Calls:           {r.get('calls', 0)}")
    print(f"  Avg input tok:   {float(r.get('avg_input', 0)):,.0f}")
    print(f"  Avg output tok:  {float(r.get('avg_output', 0)):,.0f}")
    print(f"  Avg cache read:  {float(r.get('avg_cache_read', 0)):,.0f}")
    print(f"  Avg latency:     {float(r.get('avg_latency_ms', 0)):,.0f} ms")
    print(f"  Max latency:     {float(r.get('max_latency_ms', 0)):,.0f} ms")
    print(f"  Avg reply len:   {float(r.get('avg_reply_len', 0)):,.0f} chars")
    print(f"  Max reply len:   {float(r.get('max_reply_len', 0)):,.0f} chars")
    print(f"  Avg cost/call:   ${float(r.get('avg_cost', 0)):.4f}")
    print(f"  Total cost:      ${float(r.get('total_cost', 0)):.4f}")


def agent_by_hour(hours: int) -> None:
    """Agent calls broken down by hour."""
    query = """
    filter message = "agent_metrics"
    | stats count(*) as calls, avg(agent_latency_ms) as avg_ms, sum(estimated_cost_usd) as cost
      by bin(1h) as hour
    | sort hour asc
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        return
    print("\n  Hour                  Calls  Avg ms   Cost")
    print("  " + "-" * 48)
    for r in rows:
        print(f"  {r.get('hour', '?'):<22} {r.get('calls', 0):>5}  "
              f"{float(r.get('avg_ms', 0)):>6.0f}  ${float(r.get('cost', 0)):>6.4f}")


def agent_by_user(hours: int) -> None:
    """Agent calls broken down by user."""
    query = """
    filter message = "agent_metrics"
    | stats count(*) as calls, sum(estimated_cost_usd) as cost, avg(agent_latency_ms) as avg_ms
      by user_id
    | sort cost desc
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        return
    print("\n  User                    Calls  Avg ms   Cost")
    print("  " + "-" * 52)
    for r in rows:
        uid = r.get("user_id", "?")
        # Mask phone: show last 4 digits
        masked = f"...{uid[-4:]}" if len(uid) > 4 else uid
        print(f"  {masked:<24} {r.get('calls', 0):>5}  "
              f"{float(r.get('avg_ms', 0)):>6.0f}  ${float(r.get('cost', 0)):>6.4f}")


# ---------------------------------------------------------------------------
# Cost breakdown
# ---------------------------------------------------------------------------
def cost_breakdown(hours: int) -> None:
    """Detailed cost analysis."""
    # Agent costs
    agent_query = """
    filter message = "agent_metrics"
    | stats
        sum(input_tokens) as total_input,
        sum(output_tokens) as total_output,
        sum(cache_read_tokens) as total_cache_read,
        sum(cache_write_tokens) as total_cache_write,
        sum(estimated_cost_usd) as total_cost,
        count(*) as calls
    """
    rows = _run_query(SMS_LOG_GROUP, agent_query, hours)
    if rows:
        r = rows[0]
        print(f"  Agent (Sonnet):")
        print(f"    Calls:        {r.get('calls', 0)}")
        print(f"    Input tokens: {float(r.get('total_input', 0)):,.0f}")
        print(f"    Output tokens:{float(r.get('total_output', 0)):,.0f}")
        print(f"    Cache read:   {float(r.get('total_cache_read', 0)):,.0f}")
        print(f"    Cache write:  {float(r.get('total_cache_write', 0)):,.0f}")
        print(f"    Total cost:   ${float(r.get('total_cost', 0)):.4f}")

    # Classifier costs
    cls_query = """
    filter message = "classifier_metrics"
    | stats
        sum(input_tokens) as total_input,
        sum(output_tokens) as total_output,
        count(*) as calls
    """
    rows = _run_query(SMS_LOG_GROUP, cls_query, hours)
    if rows:
        r = rows[0]
        inp = float(r.get("total_input", 0))
        out = float(r.get("total_output", 0))
        cost = inp * PRICING["haiku_input"] + out * PRICING["haiku_output"]
        print(f"\n  Classifier (Haiku):")
        print(f"    Calls:        {r.get('calls', 0)}")
        print(f"    Input tokens: {inp:,.0f}")
        print(f"    Output tokens:{out:,.0f}")
        print(f"    Total cost:   ${cost:.4f}")

    # Projected monthly
    if rows:
        agent_cost = float(rows[0].get("total_cost", 0)) if rows else 0
        # Re-fetch agent cost
        arows = _run_query(SMS_LOG_GROUP, agent_query, hours)
        agent_cost = float(arows[0].get("total_cost", 0)) if arows else 0
        daily_rate = (agent_cost + cost) / max(hours / 24, 1)
        print(f"\n  Projected monthly: ${daily_rate * 30:.2f}")


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------
def quality_report(hours: int) -> None:
    """Response quality analysis from validation warnings."""
    query = """
    filter message = "validation_warning"
    | stats count(*) as occurrences by check
    | sort occurrences desc
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        print("  No validation warnings found. All responses clean.")
        return

    for r in rows:
        print(f"  {r.get('check', '?')}: {r.get('occurrences', 0)} occurrences")

    # Response length distribution
    len_query = """
    filter message = "agent_metrics"
    | stats
        avg(reply_length) as avg_len,
        max(reply_length) as max_len,
        count(reply_length > 480) as over_limit,
        count(reply_length > 300) as over_target,
        count(*) as total
    """
    rows = _run_query(SMS_LOG_GROUP, len_query, hours)
    if rows:
        r = rows[0]
        total = int(r.get("total", 1))
        over_limit = int(r.get("over_limit", 0))
        over_target = int(r.get("over_target", 0))
        print(f"\n  Response lengths:")
        print(f"    Average:       {float(r.get('avg_len', 0)):,.0f} chars")
        print(f"    Max:           {float(r.get('max_len', 0)):,.0f} chars")
        print(f"    Over 480 (limit): {over_limit} / {total}")
        print(f"    Over 300 (target): {over_target} / {total}")


# ---------------------------------------------------------------------------
# Classifier breakdown
# ---------------------------------------------------------------------------
def classifier_report(hours: int) -> None:
    """Intent classification breakdown."""
    query = """
    filter message = "classifier_metrics"
    | stats count(*) as calls, avg(classifier_latency_ms) as avg_ms by intent
    | sort calls desc
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        print("  No classifier calls found.")
        return

    total = sum(int(r.get("calls", 0)) for r in rows)
    print(f"  Intent               Calls   %     Avg ms")
    print("  " + "-" * 46)
    for r in rows:
        calls = int(r.get("calls", 0))
        pct = (calls / total * 100) if total else 0
        print(f"  {r.get('intent', '?'):<20} {calls:>5}  {pct:>5.1f}%  "
              f"{float(r.get('avg_ms', 0)):>6.0f}")


# ---------------------------------------------------------------------------
# Scheduler stats
# ---------------------------------------------------------------------------
def scheduler_report(hours: int) -> None:
    """Scheduler run statistics."""
    query = """
    filter message = "scheduler_metrics"
    | stats
        count(*) as runs,
        avg(users_processed) as avg_users,
        sum(sent_count) as total_sent,
        sum(error_count) as total_errors,
        avg(run_duration_ms) as avg_duration_ms,
        max(run_duration_ms) as max_duration_ms
    """
    rows = _run_query(SCHEDULER_LOG_GROUP, query, hours)
    if not rows:
        print("  No scheduler runs found.")
        return

    r = rows[0]
    print(f"  Runs:            {r.get('runs', 0)}")
    print(f"  Avg users/run:   {float(r.get('avg_users', 0)):.1f}")
    print(f"  Messages sent:   {r.get('total_sent', 0)}")
    print(f"  Errors:          {r.get('total_errors', 0)}")
    print(f"  Avg duration:    {float(r.get('avg_duration_ms', 0)):,.0f} ms")
    print(f"  Max duration:    {float(r.get('max_duration_ms', 0)):,.0f} ms")

    # By message type
    type_query = """
    filter message = "Proactive message sent"
    | stats count(*) as sent by message_type
    | sort sent desc
    """
    rows = _run_query(SCHEDULER_LOG_GROUP, type_query, hours)
    if rows:
        print(f"\n  By message type:")
        for r in rows:
            print(f"    {r.get('message_type', '?')}: {r.get('sent', 0)}")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_csv(hours: int) -> None:
    """Export raw agent_metrics to CSV."""
    query = """
    filter message = "agent_metrics"
    | fields @timestamp, user_id, prompt_version, input_tokens, output_tokens,
             cache_read_tokens, agent_latency_ms, estimated_cost_usd, reply_length, is_new_user
    | sort @timestamp asc
    """
    rows = _run_query(SMS_LOG_GROUP, query, hours)
    if not rows:
        print("No data to export.")
        return

    # Header
    keys = ["@timestamp", "user_id", "prompt_version", "input_tokens", "output_tokens",
            "cache_read_tokens", "agent_latency_ms", "estimated_cost_usd", "reply_length", "is_new_user"]
    print(",".join(keys))
    for r in rows:
        print(",".join(str(r.get(k, "")) for k in keys))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Stride production analytics")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours (default: 24)")
    parser.add_argument("--cost", action="store_true", help="Cost breakdown")
    parser.add_argument("--quality", action="store_true", help="Response quality report")
    parser.add_argument("--classifier", action="store_true", help="Classifier intent breakdown")
    parser.add_argument("--scheduler", action="store_true", help="Scheduler run stats")
    parser.add_argument("--all", action="store_true", help="Run all reports")
    parser.add_argument("--export", choices=["csv"], help="Export raw data")
    args = parser.parse_args()

    if args.export == "csv":
        export_csv(args.hours)
        return

    show_all = args.all or not any([args.cost, args.quality, args.classifier, args.scheduler])

    print(f"\n{'='*56}")
    print(f"  Stride Analytics — last {args.hours}h")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*56}")

    if show_all or not any([args.cost, args.quality, args.classifier, args.scheduler]):
        print(f"\n--- Agent Summary ---")
        agent_summary(args.hours)
        agent_by_hour(args.hours)
        agent_by_user(args.hours)

    if show_all or args.cost:
        print(f"\n--- Cost Breakdown ---")
        cost_breakdown(args.hours)

    if show_all or args.quality:
        print(f"\n--- Response Quality ---")
        quality_report(args.hours)

    if show_all or args.classifier:
        print(f"\n--- Classifier ---")
        classifier_report(args.hours)

    if show_all or args.scheduler:
        print(f"\n--- Scheduler ---")
        scheduler_report(args.hours)

    print()


if __name__ == "__main__":
    main()

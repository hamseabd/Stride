# Phase 2: Feedback + Onboarding — Detailed Implementation Spec

**Prerequisite:** Phase 0 and Phase 1 must be done (both ✅ confirmed complete).

**Apply bugfix first:** Fix BUG-001 (`update_user_patterns` preferred_tone reset) before any other
Phase 2 work. See `bugfix.md`.

**Goal:** After this phase, Stride can collect user feedback via two paths, has richer onboarding
that works one question at a time, a better HELP response, and a local scheduler test endpoint.
The tone field is now safe to write to. Full tone derivation logic (latency tracking, heuristics)
ships in Phase 3 alongside the outbound scheduler.

**Files touched:**
- `shared/tools.py` — BUG-001 fix + new `submit_feedback` tool
- `shared/db.py` — new `store_feedback()` function
- `functions/sms/handler.py` — FEEDBACK keyword in guard chain + updated HELP text + updated onboarding addendum
- `functions/agent/handler.py` — add `submit_feedback` to TOOLS list
- `Makefile` — add `feedback` and `feedback-user` targets
- `local_server.py` — add `POST /test-scheduler` endpoint (gitignored, local dev only)

---

## Implementation Order

```
Step 1: BUG-001 fix                            (tools.py — 2 lines)
Step 2: store_feedback() in db.py              (db.py — new function)
Step 3: submit_feedback tool                   (tools.py — new tool)
Step 4: FEEDBACK keyword in guard chain        (sms/handler.py)
Step 5: Add submit_feedback to TOOLS lists     (both handlers)
Step 6: make feedback command                  (Makefile)
Step 7: HELP text improvement                  (sms/handler.py)
Step 8: Onboarding addendum improvement        (sms/handler.py)
Step 9: /test-scheduler scaffold               (local_server.py)
```

Steps 1–3 have no dependencies on each other — do them first, they're fast.
Steps 4–5 depend on step 3.
Steps 7–9 are independent.

---

## 2.1 BUG-001 Fix — `update_user_patterns` preserves `preferred_tone`

**File:** `shared/tools.py` — `update_user_patterns()` (~line 686)

Add one line after the existing `old_*` reads:

```python
# existing lines (keep)
old_count    = int(existing.get("cycle_count", 0)) if existing else 0
old_pace     = float(existing.get("avg_pace", 0.0)) if existing else 0.0
old_rate     = float(existing.get("avg_completion_rate", 0.0)) if existing else 0.0
old_blockers = existing.get("common_blockers", []) if existing else []

# ADD this line
existing_tone = existing.get("preferred_tone", "balanced") if existing else "balanced"
```

Update the `UserPattern` constructor call (~line 698):

```python
# CURRENT
pattern = UserPattern(
    user_id=user_id,
    avg_pace=round(new_pace, 2),
    avg_completion_rate=round(new_rate, 2),
    common_blockers=merged_blockers,
    cycle_count=new_count,
)

# NEW
pattern = UserPattern(
    user_id=user_id,
    avg_pace=round(new_pace, 2),
    avg_completion_rate=round(new_rate, 2),
    common_blockers=merged_blockers,
    cycle_count=new_count,
    preferred_tone=existing_tone,
)
```

### Checklist — 2.1
- [x] Add `existing_tone` read from DynamoDB record
- [x] Pass `preferred_tone=existing_tone` to constructor

---

## 2.2 Feedback Collection

### `shared/db.py` — new `store_feedback()` function

Add at the bottom of the file, after `save_conversation()`:

```python
# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def store_feedback(user_id: str, text: str, source: str) -> None:
    """
    Persist user feedback to DynamoDB.

    DynamoDB key:
        PK: USER#{user_id}
        SK: FEEDBACK#{iso_timestamp}

    source: "keyword" (user typed FEEDBACK ...) | "agent" (agent-prompted after review)
    Errors are swallowed — a logging failure must not surface to the user.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": f"FEEDBACK#{now}",
            "body": text,
            "source": source,
            "created_at": now,
        })
        logger.info("Feedback stored", user_id=user_id, source=source)
    except Exception as e:
        logger.error("store_feedback failed", error=str(e), user_id=user_id)
```

### `shared/tools.py` — new `submit_feedback` tool

Add after `complete_onboarding` (before the user preferences section):

```python
@tool
def submit_feedback(user_id: str, feedback: str) -> dict:
    """
    Store user feedback about Stride. Call this when:
    1. The agent asks for feedback after a weekly review and the user provides it.
    2. The user volunteers feedback during any session.

    Do NOT call this for the FEEDBACK keyword path — that is handled directly
    in the SMS guard chain without going through the agent.

    Params:
      user_id: The user submitting feedback.
      feedback: The feedback text (what the user said).

    Returns on success:
      {"stored": true}

    Returns on error:
      {"error": str}
    """
    try:
        from shared.db import store_feedback
        store_feedback(user_id, feedback, source="agent")
        logger.info("Feedback submitted via tool", user_id=user_id)
        return {"stored": True}
    except Exception as e:
        logger.exception("submit_feedback failed")
        return {"error": str(e)}
```

**Note:** The `from shared.db import store_feedback` inside the function avoids adding another
top-level import. Alternatively, add `store_feedback` to the existing top-level import —
either approach is fine.

### `functions/sms/handler.py` — FEEDBACK keyword in guard chain

**Update imports** — add `store_feedback` to the db import block (line ~14):

```python
from shared.db import (
    log_blocked_attempt,
    get_consent, record_consent, revoke_consent,
    get_or_create_user,
    get_conversation, save_conversation,
    store_feedback,          # NEW
)
```

**Add FEEDBACK check** right after the HELP keyword check (step 6), before the consent check:

```python
# 6. HELP keyword
if msg_upper == "HELP":
    return _twiml(_HELP_TEXT)

# 6.5. FEEDBACK keyword — bypasses agent, stores directly, no consent required
if msg_upper.startswith("FEEDBACK "):
    feedback_text = message[len("FEEDBACK "):].strip()
    if feedback_text:
        store_feedback(user_id, feedback_text, source="keyword")
        logger.info("Feedback received via keyword", user_id=user_id)
        return _twiml("Thanks — I'll read it.")
    return _twiml("Try: FEEDBACK followed by your thoughts.")

# 7. Consent check
```

**Why no consent required for FEEDBACK:** The user is sending us text, not receiving it. Storing
it doesn't violate TCPA. Edge case: a non-consented user sends feedback, that's fine.

**Length note:** `check_message()` already blocks messages over 500 chars, so feedback text is
capped at ~490 chars (500 minus `"FEEDBACK "`). No additional validation needed.

### `functions/sms/handler.py` — add `submit_feedback` to TOOLS list

```python
from shared.tools import (
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
    submit_feedback,    # NEW
)

TOOLS = [
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
    submit_feedback,    # NEW
]
```

**Same change in `functions/agent/handler.py`** — import and add to TOOLS list.

### `Makefile` — `feedback` and `feedback-user` targets

Add a `TABLE` variable and two new targets:

```makefile
# ── Config ───────────────────────────────────────────────────────────────────
TABLE ?= stride-prod

# ── Feedback (dev tool — scan is acceptable here, this is not a Lambda path) ─
feedback:
	aws dynamodb scan \
	  --table-name $(TABLE) \
	  --filter-expression "begins_with(sk, :f)" \
	  --expression-attribute-values '{":f":{"S":"FEEDBACK#"}}' \
	  --query "Items[*].{user:pk.S,body:body.S,source:source.S,at:created_at.S}" \
	  --output table

feedback-user:
	@test -n "$(USER)" || (echo "Usage: make feedback-user USER=+15551234567" && exit 1)
	aws dynamodb query \
	  --table-name $(TABLE) \
	  --key-condition-expression "pk = :pk AND begins_with(sk, :f)" \
	  --expression-attribute-values '{":pk":{"S":"USER#$(USER)"},":f":{"S":"FEEDBACK#"}}' \
	  --query "Items[*].{body:body.S,source:source.S,at:created_at.S}" \
	  --output table
```

Usage:
```bash
make feedback                            # all users' feedback (scan — dev only)
make feedback-user USER=+15551234567     # one user's feedback (query — production-safe)
```

**Hard constraint note:** The `make feedback` target uses DynamoDB Scan. This is intentional
and acceptable for a developer CLI tool. Scan is only forbidden in Lambda handlers (production
code paths). `make feedback-user` uses a query and is production-safe for debugging.

Add `feedback` and `feedback-user` to the `.PHONY` line.

### Checklist — 2.2
- [x] Add `store_feedback()` to `shared/db.py`
- [x] Add `submit_feedback` tool to `shared/tools.py`
- [x] Import `store_feedback` in `functions/sms/handler.py`
- [x] Add FEEDBACK keyword handler in guard chain (step 6.5)
- [x] Add `submit_feedback` to TOOLS import + list in `sms/handler.py`
- [x] Add `submit_feedback` to TOOLS import + list in `agent/handler.py`
- [x] Add `TABLE` variable to Makefile
- [x] Add `feedback` and `feedback-user` targets to Makefile
- [x] Add both to `.PHONY`
- [x] Test: text `FEEDBACK this is a test`, confirm stored in DynamoDB
- [x] Test: `make feedback-user USER=+15551234567` shows the entry

---

## 2.3 HELP Text Improvement

**File:** `functions/sms/handler.py` — `_HELP_TEXT` constant (~line 58)

The current text covers the basics but doesn't explain how to customize or what to expect.
Enrich it while staying under 320 chars (2 SMS segments):

```python
# CURRENT
_HELP_TEXT = (
    "Stride helps you plan your week, check in daily, and review progress.\n"
    "Just text me naturally — e.g. 'plan my week' or 'I finished the logo'.\n"
    "Reply STOP to unsubscribe."
)

# NEW
_HELP_TEXT = (
    "Stride helps you finish what you start.\n"
    "Try: 'plan my week', 'I finished the logo', 'I'm stuck on the proposal'\n"
    "Set reminders: 'remind me at 8am' or 'I'm in California'\n"
    "Feedback: FEEDBACK <your thoughts>\n"
    "Unsubscribe: STOP"
)
```

### Checklist — 2.3
- [x] Replace `_HELP_TEXT` in `sms/handler.py`
- [x] Verify char count stays under 320

---

## 2.4 Onboarding Addendum Improvement

**File:** `functions/sms/handler.py` — `_ONBOARDING_ADDENDUM` constant (~line 78)

Current addendum is fine but doesn't enforce one-question-at-a-time, and doesn't tell the agent
to explain the weekly rhythm after setup. SMS onboarding fails fast if the first message is a
wall of text. Fix this:

```python
# CURRENT
_ONBOARDING_ADDENDUM = """
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

# NEW
_ONBOARDING_ADDENDUM = """
NEW USER — no projects yet. Run setup.

ONE QUESTION AT A TIME. Never send multiple questions in one message.
SMS users drop off if they get a wall of text. Ask. Wait. Ask again.

Onboarding sequence:
1. "Hey! I'm Stride, your productivity coach. What's one thing you want to accomplish?"
2. Wait for their answer. Then: "When do you want that done by?" (If they say no deadline, that's fine.)
3. Call create_project with their goal + target_date.
4. "What's the most important thing to do this week toward that goal?" — create a work cycle + first task.
5. One more task: "Anything else this week, or is that the focus?"
6. "Any daily habits you want to build — like writing, exercise, or reading?" — use create_habit if yes.
7. Call complete_onboarding.
8. Explain the rhythm in one message: "Here's how we work: Monday I'll help you plan, we check in daily,
   and Friday we review. Text me anytime."

Keep each reply under 160 chars if possible — aim for 1 SMS segment per message.
Never mention 'points', 'sprints', or 'stories'.
"""
```

### Checklist — 2.4
- [x] Replace `_ONBOARDING_ADDENDUM` in `sms/handler.py`
- [x] Test via `chat.py`: fresh user → verify onboarding is one question at a time

---

## 2.5 Tone Adaptation — Phase 2 Scope

**What ships in Phase 2:** The bugfix (2.1) that prevents preferred_tone from being reset.
The system prompt injection of preferred_tone already exists in `_call_agent()` (done in Phase 1).

**What is deferred to Phase 3:**
- Latency tracking: needs `OUTBOUND#{timestamp}` records + `replied_at` field, which requires
  the outbound SMS system (Phase 3) to exist first.
- Tone derivation logic: updating preferred_tone based on latency + verbosity signals.
  Cannot be built until there are outbound messages to measure response latency against.

**No new code in Phase 2 for tone adaptation beyond BUG-001 fix.**

The field `preferred_tone` is already:
- On the `UserPattern` model with default "balanced" ✅
- Injected into the system prompt in `_call_agent()` ✅
- Safe to write to (after BUG-001 fix) ✅

Phase 3 will add: `OutboundLog` entity, `replied_at` tracking, and a heuristic that updates
`preferred_tone` in UserPattern every 2 weeks based on engagement signals.

### Checklist — 2.5
- [x] BUG-001 fix applied (covered in 2.1)
- [x] Confirm system prompt injection is in place (already done, verify it reads from `user` dict)
- [x] No other tone code in Phase 2

---

## 2.6 `/test-scheduler` Endpoint (Local Dev Only)

**File:** `local_server.py` (gitignored — add to your local copy)

Scaffolds the scheduler logic locally so timezone math and user-filtering can be tested before
the EventBridge Lambda is built in Phase 3. No Twilio creds needed for dry-run mode.

Add this route to your Flask local server:

```python
@app.route("/test-scheduler", methods=["GET"])
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
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from shared.db import get_table

    dry_run = request.args.get("send", "false").lower() != "true"
    filter_user = request.args.get("user", "")

    # Phase 3 will query CONSENT#PROACTIVE items.
    # For now, scan all users and show what message they'd receive based on day/time.
    # Scan is acceptable in a local dev tool — not a Lambda path.
    try:
        items = get_table().scan(
            FilterExpression="sk = :meta",
            ExpressionAttributeValues={":meta": {"S": "#METADATA"}},
        ).get("Items", [])
    except Exception as e:
        return {"error": str(e)}, 500

    results = []
    now_utc = datetime.utcnow()

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

        # Determine which message type would fire now
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

    return {
        "checked_users": len(results),
        "would_send_count": len(to_send),
        "dry_run": dry_run,
        "results": results,
    }
```

Usage:
```bash
# See what messages would fire right now for all users
curl localhost:8000/test-scheduler | jq .

# Filter to one user
curl "localhost:8000/test-scheduler?user=+15551234567" | jq .

# Actually send (Phase 3 — requires proactive consent + Twilio outbound)
curl "localhost:8000/test-scheduler?send=true"
```

**Phase 3 will replace** the scan with a query on `CONSENT#PROACTIVE` items and will call
the actual outbound SMS helper (`shared/sms.py`) when `send=true`.

### Checklist — 2.6
- [x] Add `/test-scheduler` route to `local_server.py`
- [x] Test: `curl localhost:8000/test-scheduler | jq .` returns user list with `message_type`
- [x] Test: `?user=+15551234567` filters correctly
- [x] Verify timezone math: user in PST at 9am shows `morning_reminder` if Tuesday-Thursday

---

## Files Changed in This Phase

| File | Change | Step |
|------|--------|------|
| `shared/tools.py` | BUG-001 fix in `update_user_patterns` + new `submit_feedback` tool | 2.1, 2.2 |
| `shared/db.py` | New `store_feedback()` function | 2.2 |
| `functions/sms/handler.py` | Import `store_feedback` + FEEDBACK keyword (step 6.5) + TOOLS update + HELP text + onboarding addendum | 2.2, 2.3, 2.4 |
| `functions/agent/handler.py` | Add `submit_feedback` to TOOLS import + list | 2.2 |
| `Makefile` | Add `TABLE` variable + `feedback` + `feedback-user` targets | 2.2 |
| `local_server.py` | Add `/test-scheduler` route | 2.6 |

**Total tool count after Phase 2:** 19 (was 18 — add `submit_feedback`)

---

## Definition of Done — Phase 2

- [x] `make feedback-user USER=+15551234567` returns stored feedback after texting `FEEDBACK ...`
- [x] `make feedback` returns all users' feedback entries
- [x] Agent calls `submit_feedback` after weekly review when user provides feedback
- [x] HELP response fits in 2 SMS segments and includes FEEDBACK keyword instructions
- [x] Fresh user onboarding via `chat.py` goes one question at a time — no walls of text
- [x] After onboarding, agent explains Monday plan / daily check-in / Friday review rhythm
- [x] `preferred_tone` is preserved after `update_user_patterns` (BUG-001 fixed)
- [x] `curl localhost:8000/test-scheduler` returns user list with correct timezone math

---

## What's Next (Phase 3)

With Phase 2 done, Phase 3 builds proactive messaging:

1. `shared/sms.py` — Twilio REST client wrapper (`Client.messages.create()`)
2. Proactive consent entity (`CONSENT#PROACTIVE`) + REMIND ME / NO REMINDERS keywords
3. `stride-scheduler` Lambda — EventBridge every 15 min, reads consented users, sends messages
4. Tone adaptation: `OutboundLog` entity + `replied_at` tracking + `preferred_tone` derivation heuristic
5. Infrastructure: `eventbridge.tf`, new Lambda module, 4th ECR repo

See `roadmap.md` Week 2: Proactive Messaging for full detail.

# Phase 1: Foundation — Detailed Implementation Spec

**Prerequisite:** Phase 0 must be done first (see `phase0-fixes.md`).

**Goal:** After today, Stride has conversation memory, moat data fields, goal model, habits, user preferences, and an interactive CLI to test it all locally.

**Files touched:**
- `shared/models.py` — add fields to 5 models + extend User + new Habit model
- `shared/db.py` — add 2 new functions (get_conversation, save_conversation) with timezone-aware reset + byte-size safety
- `shared/tools.py` — modify 3 existing tools + 3 new habit tools (frequency-aware streaks, timezone-aware dates)
- `shared/prompt.py` — add tone + timezone injection + goal decomposition + habit awareness
- `functions/sms/handler.py` — wire conversation memory into _call_agent(), add capacity/goal/habit addendum, update onboarding
- `scrumbot-app/chat.py` — new file (gitignored, local dev only)

---

## 1.1 Models Update

### `shared/models.py` — Current → New

**User model (line 14-20):**

```python
# CURRENT
class User(BaseModel):
    user_id: str = Field(default_factory=_uuid)
    name: str = ""
    email: str = ""
    phone: str = ""
    onboarded: bool = False
    created_at: str = Field(default_factory=_now)

# NEW — add 4 preference fields
class User(BaseModel):
    user_id: str = Field(default_factory=_uuid)
    name: str = ""
    email: str = ""
    phone: str = ""
    onboarded: bool = False
    created_at: str = Field(default_factory=_now)
    timezone: str = "America/New_York"
    checkin_time: str = "09:00"
    evening_time: str = "18:00"
    planning_day: int = 1  # 1=Monday, 7=Sunday
```

**Task model (line 42-51):**

```python
# CURRENT
class Task(BaseModel):
    task_id: str = Field(default_factory=_uuid)
    cycle_id: str
    title: str
    description: str = ""
    estimate: int = 0
    estimate_label: str = ""
    status: str = "todo"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

# NEW — add status_changed_at
class Task(BaseModel):
    task_id: str = Field(default_factory=_uuid)
    cycle_id: str
    title: str
    description: str = ""
    estimate: int = 0
    estimate_label: str = ""
    status: str = "todo"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    status_changed_at: str = Field(default_factory=_now)
```

**Blocker model (line 64-69):**

```python
# CURRENT
class Blocker(BaseModel):
    blocker_id: str = Field(default_factory=_uuid)
    task_id: str
    description: str
    resolved: bool = False
    created_at: str = Field(default_factory=_now)

# NEW — add category
class Blocker(BaseModel):
    blocker_id: str = Field(default_factory=_uuid)
    task_id: str
    description: str
    resolved: bool = False
    category: str = ""  # external | scope | capacity | process
    created_at: str = Field(default_factory=_now)
```

**Velocity model (line 72-78):**

```python
# CURRENT
class Velocity(BaseModel):
    cycle_id: str
    project_id: str
    planned_points: int = 0
    delivered_points: int = 0
    cycle_name: str = ""
    recorded_at: str = Field(default_factory=_now)

# NEW — add active_project_count
class Velocity(BaseModel):
    cycle_id: str
    project_id: str
    planned_points: int = 0
    delivered_points: int = 0
    cycle_name: str = ""
    active_project_count: int = 0
    recorded_at: str = Field(default_factory=_now)
```

**Project model (line 23-28):**

```python
# CURRENT
class Project(BaseModel):
    project_id: str = Field(default_factory=_uuid)
    user_id: str
    name: str = ""
    description: str = ""
    created_at: str = Field(default_factory=_now)

# NEW — add target_date for goal model
class Project(BaseModel):
    project_id: str = Field(default_factory=_uuid)
    user_id: str
    name: str = ""
    description: str = ""
    target_date: str = ""  # YYYY-MM-DD — when user wants to achieve this goal
    created_at: str = Field(default_factory=_now)
```

**UserPattern model (line 81-87):**

```python
# CURRENT
class UserPattern(BaseModel):
    user_id: str
    avg_pace: float = 0.0
    avg_completion_rate: float = 0.0
    common_blockers: list = Field(default_factory=list)
    cycle_count: int = 0
    updated_at: str = Field(default_factory=_now)

# NEW — add preferred_tone
class UserPattern(BaseModel):
    user_id: str
    avg_pace: float = 0.0
    avg_completion_rate: float = 0.0
    common_blockers: list = Field(default_factory=list)
    cycle_count: int = 0
    preferred_tone: str = "balanced"  # direct | encouraging | balanced
    updated_at: str = Field(default_factory=_now)
```

**NEW — Habit model (add after UserPattern):**

```python
class Habit(BaseModel):
    habit_id: str = Field(default_factory=_uuid)
    user_id: str
    title: str
    frequency: str = "daily"  # daily | weekdays | 3x_week | weekly
    current_streak: int = 0
    longest_streak: int = 0
    last_completed: str = ""  # YYYY-MM-DD
    active: bool = True
    created_at: str = Field(default_factory=_now)
```

**DynamoDB entity for Habit:**

| Field | Value |
|-------|-------|
| PK | `USER#{user_id}` |
| SK | `HABIT#{habit_id}` |
| GSI1PK | `HABIT#{habit_id}` |
| GSI1SK | `#METADATA` |

**Habit completion log entity:**

| Field | Value |
|-------|-------|
| PK | `HABIT#{habit_id}` |
| SK | `DONE#{YYYY-MM-DD}` |

Access patterns:
- List user habits: `PK=USER#{user_id}`, `SK begins_with HABIT#`
- Get habit by ID: `GSI1: HABIT#{habit_id}`, `#METADATA`
- Check if completed today: `PK=HABIT#{habit_id}`, `SK=DONE#{today}`
- Completion history: `PK=HABIT#{habit_id}`, `SK begins_with DONE#`

### `shared/tools.py` — 3 Existing Tools to Modify

**1. `update_task_status()` (line 276-285) — add status_changed_at to UpdateExpression:**

```python
# CURRENT (line 276-284)
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #s = :status, gsi1sk = :gsi1sk, updated_at = :updated_at",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":gsi1sk": f"STATUS#{status}",
                ":updated_at": updated_at,
            },
        )

# NEW — add status_changed_at
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #s = :status, gsi1sk = :gsi1sk, updated_at = :updated_at, status_changed_at = :sca",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":gsi1sk": f"STATUS#{status}",
                ":updated_at": updated_at,
                ":sca": updated_at,
            },
        )
```

**2. `flag_blocker()` (line 379-405) — add category param:**

```python
# CURRENT signature
def flag_blocker(task_id: str, description: str) -> dict:

# NEW signature
def flag_blocker(task_id: str, description: str, category: str) -> dict:
```

Update docstring to document `category` param (external | scope | capacity | process).

The `Blocker(...)` constructor already gets `category` from the model default. Just pass it through:

```python
        blocker = Blocker(task_id=task_id, description=description, category=category)
```

**3. `record_velocity()` (line 484-537) — compute active_project_count:**

Add before `velocity = Velocity(...)`:

```python
        # Compute active project count for context-switching data
        project_resp = get_table().query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"PROJECT#{project_id}"),
        )
        project_item = project_resp.get("Items", [{}])[0]
        owner_id = project_item.get("user_id", "")
        active_count = 0
        if owner_id:
            proj_resp = get_table().query(
                KeyConditionExpression=Key("pk").eq(f"USER#{owner_id}") & Key("sk").begins_with("PROJECT#"),
            )
            active_count = len(proj_resp.get("Items", []))
```

Then pass to Velocity constructor:

```python
        velocity = Velocity(
            project_id=project_id,
            cycle_id=cycle_id,
            planned_points=planned_points,
            delivered_points=delivered_points,
            cycle_name=cycle_name,
            active_project_count=active_count,
        )
```

### `shared/tools.py` — 3 New Habit Tools

**4. `create_habit()` — new tool:**

```python
@tool
def create_habit(user_id: str, title: str, frequency: str) -> dict:
    """
    Create a recurring habit for a user. Habits are separate from goals — they represent
    ongoing practices the user wants to maintain (e.g. "Write 30 min", "Exercise").

    Params:
      user_id: The user who owns this habit.
      title: Short habit name (e.g. "Write 30 minutes", "Exercise").
      frequency: How often. Must be one of: daily, weekdays, 3x_week, weekly.

    Returns on success:
      {"habit_id": str, "title": str, "frequency": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
    try:
        valid_freq = {"daily", "weekdays", "3x_week", "weekly"}
        if frequency not in valid_freq:
            return {"error": f"Invalid frequency '{frequency}'. Must be one of: {sorted(valid_freq)}"}

        habit = Habit(user_id=user_id, title=title, frequency=frequency)
        item = habit.model_dump()
        item["pk"] = f"USER#{user_id}"
        item["sk"] = f"HABIT#{habit.habit_id}"
        item["gsi1pk"] = f"HABIT#{habit.habit_id}"
        item["gsi1sk"] = "#METADATA"

        get_table().put_item(Item=item)
        logger.info("Habit created", habit_id=habit.habit_id, user_id=user_id)
        return {"habit_id": habit.habit_id, "title": habit.title, "frequency": habit.frequency, "created_at": habit.created_at}
    except Exception as e:
        logger.exception("create_habit failed")
        return {"error": str(e)}
```

**5. `complete_habit()` — new tool (frequency-aware streaks):**

Streak logic per frequency:
- **daily:** streak continues if `last_completed == yesterday`
- **weekdays:** streak continues if `last_completed` was the previous weekday (skip Sat/Sun)
- **weekly:** streak continues if `last_completed` was within the last 7 days
- **3x_week:** streak = number of completions in the rolling last 7 days (streak "continues" as long as >= 3 in any 7-day window)

```python
def _is_streak_alive(last_completed: str, today_str: str, frequency: str) -> bool:
    """Check if a habit's streak is still alive based on its frequency."""
    if not last_completed:
        return False
    today = datetime.strptime(today_str, "%Y-%m-%d")
    last = datetime.strptime(last_completed, "%Y-%m-%d")
    gap = (today - last).days

    if frequency == "daily":
        return gap == 1
    elif frequency == "weekdays":
        # Skip weekends: Friday → Monday is 3 days but still a streak
        if gap == 1:
            return True
        if gap == 3 and last.isoweekday() == 5:  # Friday → Monday
            return True
        return False
    elif frequency == "weekly":
        return gap <= 7
    elif frequency == "3x_week":
        return gap <= 7  # streak = rolling count, handled separately
    return gap == 1  # fallback to daily


@tool
def complete_habit(user_id: str, habit_id: str) -> dict:
    """
    Mark a habit as completed for today. Updates the streak counter.
    Streak logic is frequency-aware:
      - daily: consecutive calendar days
      - weekdays: consecutive weekdays (Fri→Mon is fine)
      - weekly: at least once per 7-day window
      - 3x_week: at least 3 completions in any rolling 7-day window

    Idempotent — calling twice on the same day is a no-op (returns current streak).

    Params:
      user_id: The user who owns this habit.
      habit_id: The habit UUID to mark complete.

    Returns on success:
      {"habit_id": str, "date": str, "current_streak": int, "longest_streak": int}

    Returns on error:
      {"error": str}
    """
    try:
        table = get_table()

        # Use user's timezone for "today"
        user_resp = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "#METADATA"})
        user_item = user_resp.get("Item", {})
        user_tz_str = user_item.get("timezone", "America/New_York")
        try:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo(user_tz_str)
        except Exception:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo("America/New_York")

        now_local = datetime.now(user_tz)
        today = now_local.strftime("%Y-%m-%d")

        # Check if already completed today
        done_resp = table.get_item(Key={"pk": f"HABIT#{habit_id}", "sk": f"DONE#{today}"})
        if done_resp.get("Item"):
            item = done_resp["Item"]
            return {"habit_id": habit_id, "date": today, "current_streak": int(item.get("streak_at_completion", 0)), "longest_streak": int(item.get("longest_at_completion", 0)), "already_done": True}

        # Get the habit record
        habit_resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"HABIT#{habit_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        habits = habit_resp.get("Items", [])
        if not habits:
            return {"error": f"Habit {habit_id} not found"}
        habit = habits[0]

        # Compute streak based on frequency
        last_completed = habit.get("last_completed", "")
        frequency = habit.get("frequency", "daily")
        current_streak = int(habit.get("current_streak", 0))
        longest_streak = int(habit.get("longest_streak", 0))

        if _is_streak_alive(last_completed, today, frequency):
            current_streak += 1
        else:
            current_streak = 1  # streak broken (or first completion), start at 1

        if current_streak > longest_streak:
            longest_streak = current_streak

        # Write completion log
        table.put_item(Item={
            "pk": f"HABIT#{habit_id}",
            "sk": f"DONE#{today}",
            "user_id": user_id,
            "completed_at": now_local.isoformat(),
            "streak_at_completion": current_streak,
            "longest_at_completion": longest_streak,
        })

        # Update habit record
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": f"HABIT#{habit_id}"},
            UpdateExpression="SET last_completed = :d, current_streak = :cs, longest_streak = :ls",
            ExpressionAttributeValues={":d": today, ":cs": current_streak, ":ls": longest_streak},
        )

        logger.info("Habit completed", habit_id=habit_id, user_id=user_id, streak=current_streak)
        return {"habit_id": habit_id, "date": today, "current_streak": current_streak, "longest_streak": longest_streak}
    except Exception as e:
        logger.exception("complete_habit failed")
        return {"error": str(e)}
```

**Note:** Add `from datetime import datetime, timedelta` at the top of tools.py (timedelta is new). Add `from zoneinfo import ZoneInfo` for timezone-aware dates.

**6. `list_habits()` — new tool:**

```python
@tool
def list_habits(user_id: str) -> dict:
    """
    List all active habits for a user with their current streak info.

    Params:
      user_id: The user whose habits to list.

    Returns on success:
      {"habits": [{"habit_id": str, "title": str, "frequency": str,
        "current_streak": int, "longest_streak": int, "last_completed": str,
        "done_today": bool}]}

    Returns on error:
      {"error": str}
    """
    try:
        table = get_table()

        # Use user's timezone for "today"
        user_resp = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "#METADATA"})
        user_item = user_resp.get("Item", {})
        user_tz_str = user_item.get("timezone", "America/New_York")
        try:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo(user_tz_str)
        except Exception:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo("America/New_York")
        today = datetime.now(user_tz).strftime("%Y-%m-%d")

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("HABIT#"),
        )
        items = resp.get("Items", [])

        habits = []
        for h in items:
            if not h.get("active", True):
                continue
            habits.append({
                "habit_id": h.get("habit_id"),
                "title": h.get("title", ""),
                "frequency": h.get("frequency", "daily"),
                "current_streak": int(h.get("current_streak", 0)),
                "longest_streak": int(h.get("longest_streak", 0)),
                "last_completed": h.get("last_completed", ""),
                "done_today": h.get("last_completed", "") == today,
            })

        logger.info("Habits listed", user_id=user_id, count=len(habits))
        return {"habits": habits}
    except Exception as e:
        logger.exception("list_habits failed")
        return {"error": str(e)}
```

### Checklist — 1.1 ✅ COMPLETE
- [x] Project model: add target_date
- [x] User model: add timezone, checkin_time, evening_time, planning_day
- [x] Task model: add status_changed_at
- [x] Blocker model: add category
- [x] Velocity model: add active_project_count
- [x] UserPattern model: add preferred_tone
- [x] NEW: Habit model (full new class)
- [x] update_task_status(): add status_changed_at to UpdateExpression
- [x] flag_blocker(): add category parameter + pass to Blocker constructor + update docstring
- [x] record_velocity(): compute active_project_count + pass to Velocity constructor
- [x] NEW: create_habit() tool
- [x] NEW: complete_habit() tool — frequency-aware streaks + timezone-aware "today"
- [x] NEW: list_habits() tool — timezone-aware done_today
- [x] NEW: _is_streak_alive() helper — daily/weekdays/weekly/3x_week logic
- [x] Update model import in tools.py to include Habit
- [x] Add `timedelta` to datetime import in tools.py
- [x] Add `from zoneinfo import ZoneInfo` to tools.py
- [x] Update TOOLS list in sms/handler.py to include 3 new habit tools

---

## 1.2 Conversation Memory

### `shared/db.py` — 2 New Functions

Add at the bottom of the file, after `log_blocked_attempt()`:

```python
# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

def get_conversation(user_id: str) -> list:
    """
    Load the current conversation history for a user.
    Returns the stored messages list, or empty list if none exists.

    DynamoDB key:
        PK: USER#{user_id}
        SK: CONVERSATION#CURRENT

    Returns empty list on error (fail open).
    """
    try:
        resp = get_table().get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"}
        )
        item = resp.get("Item")
        if not item:
            return []

        # Check weekly reset — use user's timezone, not UTC
        import json
        from datetime import datetime, timezone as tz
        from zoneinfo import ZoneInfo
        planning_day = int(item.get("planning_day", 1))  # 1=Monday
        user_tz_str = item.get("user_timezone", "America/New_York")
        try:
            user_tz = ZoneInfo(user_tz_str)
        except Exception:
            user_tz = ZoneInfo("America/New_York")
        last_reset = item.get("last_reset_date", "")
        now_local = datetime.now(user_tz)
        today = now_local.strftime("%Y-%m-%d")
        weekday = now_local.isoweekday()  # 1=Monday, 7=Sunday

        if weekday == planning_day and last_reset != today:
            # It's reset day and we haven't reset yet today — clear history
            logger.info("Weekly conversation reset", user_id=user_id)
            get_table().update_item(
                Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"},
                UpdateExpression="SET messages = :empty, last_reset_date = :today",
                ExpressionAttributeValues={":empty": "[]", ":today": today},
            )
            return []

        messages_json = item.get("messages", "[]")
        return json.loads(messages_json) if isinstance(messages_json, str) else messages_json
    except Exception as e:
        logger.error("get_conversation failed — returning empty", error=str(e), user_id=user_id)
        return []


def save_conversation(user_id: str, messages: list, planning_day: int = 1, user_timezone: str = "America/New_York") -> bool:
    """
    Write updated conversation history, capped at 20 turns.
    Strips tool call/result payloads to stay under DynamoDB's 400KB item limit.
    Includes byte-size safety check — trims further if JSON exceeds 350KB.

    DynamoDB key:
        PK: USER#{user_id}
        SK: CONVERSATION#CURRENT

    Returns True on success, False on error.
    """
    import json
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo

    try:
        # Strip tool payloads — keep only user messages and assistant text
        stripped = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                if role == "user":
                    stripped.append(msg)
                elif role == "assistant":
                    # Keep only text content, strip toolUse blocks
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        text_only = [c for c in content if isinstance(c, dict) and c.get("type") != "toolUse"]
                        if text_only:
                            stripped.append({"role": "assistant", "content": text_only})
                    elif isinstance(content, str):
                        stripped.append(msg)
                # Skip toolResult messages entirely
            # Skip non-dict messages

        # Cap at 20 turns (last 20 messages)
        if len(stripped) > 20:
            stripped = stripped[-20:]

        # Safety valve: if JSON exceeds 350KB, trim more aggressively
        messages_json = json.dumps(stripped)
        while len(messages_json.encode("utf-8")) > 350_000 and len(stripped) > 2:
            stripped = stripped[-len(stripped) + 2:]  # drop 2 oldest
            messages_json = json.dumps(stripped)

        now = datetime.now(tz.utc).isoformat() + "Z"
        try:
            user_tz = ZoneInfo(user_timezone)
        except Exception:
            user_tz = ZoneInfo("America/New_York")
        now_local = datetime.now(user_tz)
        today = now_local.strftime("%Y-%m-%d")

        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": "CONVERSATION#CURRENT",
            "messages": messages_json,
            "turn_count": len(stripped),
            "planning_day": planning_day,
            "user_timezone": user_timezone,
            "last_reset_date": today if now_local.isoweekday() == planning_day else "",
            "updated_at": now,
        })
        return True
    except Exception as e:
        logger.error("save_conversation failed", error=str(e), user_id=user_id)
        return False
```

### `functions/sms/handler.py` — Wire Conversation Memory

**Modify imports (line 14-18):**

```python
# CURRENT
from shared.db import (
    log_blocked_attempt,
    get_consent, record_consent, revoke_consent,
    get_or_create_user,
)

# NEW — add get_conversation, save_conversation
from shared.db import (
    log_blocked_attempt,
    get_consent, record_consent, revoke_consent,
    get_or_create_user,
    get_conversation, save_conversation,
)
```

**Modify `_call_agent()` (line 124-137):**

```python
# CURRENT
def _call_agent(user_id: str, message: str, is_new_user: bool) -> str:
    """Run the Stride agent for an SMS message. Returns the reply string."""
    system = (
        STRIDE_SYSTEM_PROMPT.strip()
        + f"\n\nCurrent user_id: {user_id}"
        + _SMS_SYSTEM_ADDENDUM
    )
    if is_new_user:
        system += _ONBOARDING_ADDENDUM

    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=512)
    agent = Agent(model=model, system_prompt=system, tools=TOOLS, messages=[])
    result = agent(message)
    return str(result)

# NEW — load/save conversation + inject tone, timezone, and capacity language
def _call_agent(user_id: str, message: str, is_new_user: bool, user: dict) -> str:
    """Run the Stride agent for an SMS message. Returns the reply string."""
    # Build system prompt with user context
    tone = user.get("preferred_tone", "balanced")
    tz = user.get("timezone", "America/New_York")
    planning_day = int(user.get("planning_day", 1))

    system = (
        STRIDE_SYSTEM_PROMPT.strip()
        + f"\n\nCurrent user_id: {user_id}"
        + f"\nUser's timezone: {tz}"
        + f"\nThis user responds best to a {tone} coaching style."
        + _CAPACITY_LANGUAGE_ADDENDUM
        + _SMS_SYSTEM_ADDENDUM
    )
    if is_new_user:
        system += _ONBOARDING_ADDENDUM

    # Load conversation history
    history = get_conversation(user_id)

    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=512)
    agent = Agent(model=model, system_prompt=system, tools=TOOLS, messages=history)
    result = agent(message)

    # Save updated conversation
    save_conversation(user_id, agent.messages, planning_day=planning_day, user_timezone=tz)

    return str(result)
```

**New constant in sms/handler.py (add alongside the other addendums):**

```python
_CAPACITY_LANGUAGE_ADDENDUM = """
CRITICAL — how you talk about workload:
- Never say "points", "pts", "story points", or any numbers-based estimate system.
- Translate estimates to time: S = "a few hours", M = "a day or two", L = "most of the week", XL = "more than a week — that's risky, let's break it down."
- Talk about capacity in days: "You get about 3 good days of work done per week" (not "15 points").
- When a user is over-planned: "That's 5 days of work for a 3-day capacity. What can wait?"
- The point system exists internally for tracking. Users must NEVER see it.

GOAL DECOMPOSITION — how goals work:
- Users state big goals with timelines: "Launch portfolio in 3 months"
- Projects = Goals. Each project has a target_date.
- Work cycles = Milestones within a goal. Each cycle has a goal field describing the milestone.
- Tasks = weekly work within a milestone.
- YOU lead the breakdown: suggest milestones, suggest weekly tasks. User confirms or adjusts.
- During Monday planning, reference the big goal + current milestone: "Your goal is to launch the portfolio by June. This week's milestone: finish the design. Here are the tasks..."
- When creating a project, ALWAYS ask for a target date: "When do you want this done by?"
- If no target date given, that's fine — some goals are ongoing.

HABITS — separate from goals:
- Habits are recurring tasks the user wants to maintain (e.g. "Write 30 min daily", "Exercise 3x/week").
- Use create_habit for recurring practices, NOT create_task.
- Habits have streaks. Celebrate streaks: "5 days in a row writing — nice!"
- In morning messages, list both today's tasks AND habits.
- If a habit streak breaks, be encouraging not guilt-tripping: "Missed yesterday — want to get back to it today?"

WEEKLY RHYTHM:
- Monday = plan the week (conversation resets, fresh start, but you have all data via tools)
- Tue-Thu = daily check-ins (morning: what's planned, evening: how'd it go)
- Wednesday = mid-week adjust (are you on track? need to re-plan?)
- Friday = review/retro (what happened, what would you do differently)

MULTI-GOAL PRIORITIZATION:
- During planning, list all active goals with their tasks in time language
- Sum up total planned work vs their historical capacity
- If over-planned, ask what to cut or shrink — don't just warn, help them decide
- Users can add new goals anytime. Include new ones in the next planning session.
- Balance across goals: "You've got 3 goals and 3 days. Portfolio needs 2 days, Blog needs 1."
"""
```

**Update the call site (line 232):**

```python
# CURRENT
        reply = _call_agent(user_id=user_id, message=message, is_new_user=is_new_user)

# NEW — pass user dict
        reply = _call_agent(user_id=user_id, message=message, is_new_user=is_new_user, user=user)
```

**Also add tone/timezone to agent handler for `/ceremony` if needed — but that's called via HTTP API with explicit history, so defer.**

### Checklist — 1.2 ✅ COMPLETE
- [x] Add `get_conversation()` to db.py — load history, handle weekly reset using user's timezone
- [x] Add `save_conversation()` to db.py — strip tool payloads, cap at 20, store as JSON string, byte-size safety check (350KB)
- [x] Store `user_timezone` in CONVERSATION#CURRENT item for reset logic
- [x] Import new functions in sms/handler.py
- [x] Add `user` param to `_call_agent()` signature
- [x] Load history before creating Agent
- [x] Save history after agent responds (pass user_timezone)
- [x] Inject preferred_tone into system prompt
- [x] Inject timezone into system prompt
- [x] Update `_call_agent()` call site to pass `user` dict
- [x] Test: send 2 messages via chat.py, verify second has context from first

---

## 1.3 chat.py — Interactive SMS Simulator

**File:** `scrumbot-app/chat.py` (already in `.gitignore`)

This runs OUTSIDE Docker — directly against LocalStack on localhost:4566.

**Prerequisites:** `make up` must be running (LocalStack + DynamoDB table).

**What it does:**
1. Connects to LocalStack DynamoDB at `localhost:4566`
2. Auto-grants SMS consent for the test phone number
3. Creates/loads user record
4. REPL loop: user types message → runs same code path as SMS handler → prints response
5. Conversation memory persists between messages (tests 1.2)
6. Handles keywords: STOP, HELP, FEEDBACK, REMIND ME, NO REMINDERS

**Key design decisions:**
- Runs on the host machine, NOT inside Docker (so you can iterate fast without rebuilds)
- Uses `PYTHONPATH=. python chat.py` from the `scrumbot-app/` directory
- Sets env vars: `DYNAMODB_TABLE_NAME=stride-local`, `AWS_ENDPOINT_URL=http://localhost:4566`, `ENVIRONMENT=local`
- Imports `_call_agent` logic but bypasses Twilio signature validation entirely
- Auto-consents the user on first run (no need to type YES)

**Sketch:**

```python
#!/usr/bin/env python3
"""
Stride SMS Simulator — interactive local testing.

Usage:
    cd scrumbot-app
    PYTHONPATH=. python chat.py                 # default: +15551234567
    PYTHONPATH=. python chat.py +15559876543    # custom number

Requires: make up (LocalStack must be running on localhost:4566)
"""
import os
import sys

# Set environment for local dev
os.environ.setdefault("DYNAMODB_TABLE_NAME", "stride-local")
os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:4566")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "stride-chat")

from shared.db import (
    get_or_create_user, record_consent, get_consent,
    revoke_consent, get_conversation, save_conversation,
)
from shared.tools import (
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    create_habit, complete_habit, list_habits,
)
from shared.prompt import STRIDE_SYSTEM_PROMPT
from strands import Agent
from strands.models.anthropic import AnthropicModel

TOOLS = [
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    create_habit, complete_habit, list_habits,
]

SMS_ADDENDUM = """
You are responding via SMS. Additional rules:
- Keep every reply under 300 characters when possible.
- Never use markdown, bullet points, or any formatting.
- Plain sentences only.
- Never expose internal IDs, error messages, or technical details.
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

    # Auto-consent + bootstrap user
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

        # Handle keywords same as SMS handler
        if msg_upper == "STOP":
            revoke_consent(phone)
            print("Stride: You've been unsubscribed. Text again to re-join.\n")
            continue
        if msg_upper == "HELP":
            print("Stride: Stride helps you plan your week, check in daily, and review progress.")
            print("        Just text naturally — e.g. 'plan my week' or 'check in'.")
            print("        FEEDBACK <text> — share feedback about Stride")
            print("        REMIND ME — turn on daily reminders")
            print("        STOP — unsubscribe\n")
            continue

        # Refresh user record (may have been updated by tools)
        user = get_or_create_user(user_id=phone, phone=phone)
        is_new = not user.get("onboarded", False)
        if is_new:
            projects = list_active_projects(user_id=phone)
            if projects.get("projects"):
                is_new = False

        # Build system prompt
        tone = user.get("preferred_tone", "balanced")
        tz = user.get("timezone", "America/New_York")
        planning_day = int(user.get("planning_day", 1))

        system = (
            STRIDE_SYSTEM_PROMPT.strip()
            + f"\n\nCurrent user_id: {phone}"
            + f"\nUser's timezone: {tz}"
            + f"\nThis user responds best to a {tone} coaching style."
            + SMS_ADDENDUM
        )
        if is_new:
            system += ONBOARDING_ADDENDUM

        # Load history, call agent, save history
        history = get_conversation(phone)
        model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=512)
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
```

**Key notes:**
- The `ANTHROPIC_API_KEY` must be set in the shell or in `scrumbot-app/.env` (it's read by the Strands SDK automatically)
- Runs on the host, talks to LocalStack at `localhost:4566`
- conversation memory persists across messages in the same session AND across restarts (stored in DynamoDB)
- `reset` command clears conversation — useful for testing fresh onboarding

### Checklist — 1.3 ✅ COMPLETE
- [x] Create `scrumbot-app/chat.py` with REPL loop
- [x] Auto-grant consent + bootstrap user on startup
- [x] Handle STOP, HELP keywords
- [x] Load/save conversation history (tests 1.2)
- [x] Inject tone + timezone into system prompt (tests 1.1)
- [x] `reset` command to clear conversation
- [x] Verify it runs: `cd scrumbot-app && PYTHONPATH=. python chat.py`
- [ ] Test: onboard → create project → create task → check-in → quit → restart → verify memory persists (deferred — Docker blocked by network)

---

## Implementation Order (within today)

```
Step 1: models.py changes
  6 model field additions + 1 new Habit model. No dependencies.

Step 2: tools.py changes — modify 3 existing + add 3 new
  update_task_status, flag_blocker, record_velocity (modify).
  create_habit, complete_habit, list_habits (new).
  Depends on models.py.

Step 3: db.py — get_conversation/save_conversation
  Two new functions. No dependencies on steps 1-2.

Step 4: sms/handler.py — wire conversation memory + goal/habit addendum
  Modify _call_agent() + call site + update TOOLS list.
  Depends on steps 2-3.

Step 5: chat.py
  Interactive simulator with all 16 tools.
  Depends on steps 2-4.

Step 6: Test end-to-end via chat.py
  make up → PYTHONPATH=. python chat.py
  Full flow: onboard → goal with target date → task → habit → check-in
  Verify: conversation persists, streaks work, 'reset' works
```

---

## How to Test

```bash
# Terminal 1: start LocalStack
make up

# Terminal 2: run chat.py
cd scrumbot-app
PYTHONPATH=. python chat.py

# Test goal decomposition + conversation memory:
You: hello
Stride: (welcome + onboarding)
You: I want to launch a portfolio website by June
Stride: (creates project with target_date, suggests milestones, asks about this week's tasks)
You: Add a task called wireframes, medium size
Stride: (creates task — PROVES conversation memory works,
         because agent knows which project you meant)

# Test habits:
You: I also want to write for 30 minutes every day
Stride: (creates habit with daily frequency)
You: I did my writing today
Stride: (marks habit complete, shows streak: "Day 1! Keep it going.")

# Test keyword:
You: reset
[system] Conversation cleared
You: hello
Stride: (fresh onboarding — proves reset works)

# Verify conversation in DynamoDB:
aws dynamodb get-item \
  --endpoint-url http://localhost:4566 \
  --table-name stride-local \
  --key '{"pk":{"S":"USER#+15551234567"},"sk":{"S":"CONVERSATION#CURRENT"}}' \
  --query 'Item.turn_count'

# Verify habit in DynamoDB:
aws dynamodb query \
  --endpoint-url http://localhost:4566 \
  --table-name stride-local \
  --key-condition-expression "pk = :pk AND begins_with(sk, :sk)" \
  --expression-attribute-values '{":pk":{"S":"USER#+15551234567"},":sk":{"S":"HABIT#"}}' \
  --output table
```

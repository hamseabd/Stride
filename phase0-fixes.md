# Phase 0: Pre-Build Fixes — Existing Tool Gaps

**Goal:** Fix bugs and gaps in existing code that would cause problems the moment we build Phase 1. These are surgical changes to `shared/tools.py` and `functions/sms/handler.py` — no new features, just making what exists correct.

**Do this BEFORE Phase 1.**

---

## 0.1 `create_project` — Add `target_date` Parameter

The goal model requires projects to have deadlines. The current tool signature is `(user_id, name, description)` — no way to set a target date.

**File:** `shared/tools.py` — `create_project()` (line 23)

```python
# CURRENT signature
def create_project(user_id: str, name: str, description: str) -> dict:

# NEW signature
def create_project(user_id: str, name: str, description: str, target_date: str = "") -> dict:
```

Update docstring:
```python
    """
    Create a new project (goal) for a user and persist it to DynamoDB.

    Params:
      user_id: The user who owns this project (required).
      name: Short project name — this is the user's goal (required).
      description: What the project is about (optional, can be empty).
      target_date: When the user wants to achieve this goal, in YYYY-MM-DD format.
                   Empty string if the goal is ongoing with no deadline.

    Returns on success:
      {"project_id": str, "name": str, "target_date": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
```

Update the constructor call:
```python
        project = Project(user_id=user_id, name=name, description=description, target_date=target_date)
```

Update the return dict:
```python
        return {"project_id": project.project_id, "name": project.name, "target_date": project.target_date, "created_at": project.created_at}
```

Add date validation (if provided):
```python
        if target_date:
            try:
                datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                return {"error": f"target_date must be YYYY-MM-DD format, got: {target_date}"}
```

### Checklist — 0.1
- [x] Add `target_date: str = ""` param to `create_project()` signature
- [x] Update docstring to document target_date
- [x] Add date format validation (if non-empty)
- [x] Pass target_date to `Project(...)` constructor
- [x] Include target_date in return dict

---

## 0.2 `list_active_projects` — Return `target_date`

The agent can't reference a goal's deadline if the tool doesn't return it. Currently builds a manual response dict that omits `target_date`.

**File:** `shared/tools.py` — `list_active_projects()` (line 170-175)

```python
# CURRENT
            projects.append({
                "project_id": project_id,
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "active_cycle": active_cycle,
            })

# NEW — add target_date
            projects.append({
                "project_id": project_id,
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "target_date": p.get("target_date", ""),
                "active_cycle": active_cycle,
            })
```

Update the docstring return shape to include `target_date`.

### Checklist — 0.2
- [x] Add `target_date` to response dict in `list_active_projects()`
- [x] Update docstring to document target_date in return shape

---

## 0.3 New `update_project` Tool

User says "push my portfolio deadline to August." No tool exists to update a project. They'd have to recreate it and lose all cycle/task history.

**File:** `shared/tools.py` — new tool (add after `create_project`)

```python
@tool
def update_project(project_id: str, name: str = "", description: str = "", target_date: str = "") -> dict:
    """
    Update an existing project's name, description, or target date.
    Only non-empty fields are updated — pass empty string to leave a field unchanged.

    Params:
      project_id: The project UUID to update (required).
      name: New project name (empty string = no change).
      description: New description (empty string = no change).
      target_date: New target date in YYYY-MM-DD format (empty string = no change).

    Returns on success:
      {"project_id": str, "updated_fields": list[str]}

    Returns on error:
      {"error": str}
    """
    try:
        if not project_id:
            return {"error": "project_id is required"}

        if target_date:
            try:
                datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                return {"error": f"target_date must be YYYY-MM-DD format, got: {target_date}"}

        table = get_table()

        # Look up project via GSI1
        resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"PROJECT#{project_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        items = resp.get("Items", [])
        if not items:
            return {"error": f"Project {project_id} not found"}

        item = items[0]
        pk = item["pk"]
        sk = item["sk"]

        # Build update expression dynamically
        updates = []
        names = {}
        values = {}
        updated_fields = []

        if name:
            updates.append("#n = :name")
            names["#n"] = "name"
            values[":name"] = name
            updated_fields.append("name")
        if description:
            updates.append("description = :desc")
            values[":desc"] = description
            updated_fields.append("description")
        if target_date:
            updates.append("target_date = :td")
            values[":td"] = target_date
            updated_fields.append("target_date")

        if not updates:
            return {"error": "No fields to update — pass at least one of: name, description, target_date"}

        expr = "SET " + ", ".join(updates)
        kwargs = {"Key": {"pk": pk, "sk": sk}, "UpdateExpression": expr, "ExpressionAttributeValues": values}
        if names:
            kwargs["ExpressionAttributeNames"] = names

        table.update_item(**kwargs)
        logger.info("Project updated", project_id=project_id, fields=updated_fields)
        return {"project_id": project_id, "updated_fields": updated_fields}
    except Exception as e:
        logger.exception("update_project failed")
        return {"error": str(e)}
```

### Checklist — 0.3
- [x] Add `update_project()` tool to tools.py
- [x] Validate target_date format if non-empty
- [x] Look up project via GSI1
- [x] Build dynamic UpdateExpression for provided fields only
- [x] Add to TOOLS list in sms/handler.py
- [x] Add to TOOLS list in agent/handler.py

---

## 0.4 `set_user_preference` Tool (Moved from Phase 2)

The system prompt tells the agent about user preferences (timezone, checkin_time, planning_day). During onboarding, users will say things like "I'm in California" or "I prefer evening check-ins." Without this tool, the agent can't store those preferences.

**File:** `shared/tools.py` — new tool

```python
VALID_PREFERENCES = {
    "timezone": str,       # IANA timezone, e.g. "America/Los_Angeles"
    "checkin_time": str,   # HH:MM format, e.g. "09:00"
    "evening_time": str,   # HH:MM format, e.g. "18:00"
    "planning_day": int,   # 1=Monday, 7=Sunday
}

@tool
def set_user_preference(user_id: str, preference: str, value: str) -> dict:
    """
    Update a user preference. Call this when a user expresses a preference
    like "I'm in California" or "I prefer evening check-ins."

    Params:
      user_id: The user whose preference to update.
      preference: The preference name. Must be one of: timezone, checkin_time, evening_time, planning_day.
      value: The new value. Format depends on preference:
        - timezone: IANA timezone string (e.g. "America/Los_Angeles")
        - checkin_time: HH:MM in 24h format (e.g. "09:00")
        - evening_time: HH:MM in 24h format (e.g. "18:00")
        - planning_day: integer 1-7 where 1=Monday, 7=Sunday

    Returns on success:
      {"user_id": str, "preference": str, "value": str, "updated": true}

    Returns on error:
      {"error": str}
    """
    try:
        if preference not in VALID_PREFERENCES:
            return {"error": f"Invalid preference '{preference}'. Must be one of: {sorted(VALID_PREFERENCES.keys())}"}

        # Validate value format
        if preference in ("checkin_time", "evening_time"):
            try:
                h, m = value.split(":")
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                return {"error": f"{preference} must be HH:MM format (e.g. '09:00'), got: {value}"}

        if preference == "planning_day":
            try:
                day = int(value)
                if not 1 <= day <= 7:
                    raise ValueError
                value = day  # store as int
            except (ValueError, TypeError):
                return {"error": f"planning_day must be 1-7 (1=Monday), got: {value}"}

        table = get_table()
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": "#METADATA"},
            UpdateExpression=f"SET #pref = :val",
            ExpressionAttributeNames={"#pref": preference},
            ExpressionAttributeValues={":val": value},
        )
        logger.info("User preference updated", user_id=user_id, preference=preference)
        return {"user_id": user_id, "preference": preference, "value": str(value), "updated": True}
    except Exception as e:
        logger.exception("set_user_preference failed")
        return {"error": str(e)}
```

### Checklist — 0.4
- [x] Add `VALID_PREFERENCES` constant
- [x] Add `set_user_preference()` tool
- [x] Validate HH:MM format for time preferences
- [x] Validate 1-7 range for planning_day
- [x] Add to TOOLS list in sms/handler.py
- [x] Add to TOOLS list in agent/handler.py

---

## 0.5 Bump `max_tokens` in SMS Handler

The system prompt is growing significantly (goal decomposition, habits, capacity language, weekly rhythm, tone). With `max_tokens=512`, the agent's response can cut off mid-thought during complex interactions like onboarding.

The agent handler already uses `max_tokens=1024`. SMS responses are truncated at 1600 chars anyway — the limit protects SMS length, not token budget.

**File:** `functions/sms/handler.py` — `_call_agent()` (line 135)

```python
# CURRENT
    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=512)

# NEW
    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
```

### Checklist — 0.5
- [x] Change max_tokens from 512 to 1024 in `_call_agent()`

---

## Implementation Order

```
Step 1: create_project — add target_date param         (0.1)
Step 2: list_active_projects — return target_date       (0.2)
Step 3: update_project — new tool                       (0.3)
Step 4: set_user_preference — new tool                  (0.4)
Step 5: max_tokens 512 → 1024                           (0.5)
Step 6: Update TOOLS lists in handlers                  (all)
```

Steps 1-5 are independent. Step 6 depends on 3-4 being done.

---

## Full Checklist — Phase 0 ✅ COMPLETE

- [x] 0.1: Add `target_date` param to `create_project()`
- [x] 0.1: Validate date format
- [x] 0.1: Include target_date in return dict
- [x] 0.2: Return `target_date` in `list_active_projects()` response
- [x] 0.2: Update docstring
- [x] 0.3: Add `update_project()` tool with dynamic UpdateExpression
- [x] 0.4: Add `set_user_preference()` tool with validation
- [x] 0.5: Bump max_tokens to 1024
- [x] Update TOOLS list in `functions/sms/handler.py`
- [x] Update TOOLS list in `functions/agent/handler.py`
- [x] Update TOOLS import in both handlers
- [x] Test via existing local setup: create project with target_date, update it, set preference

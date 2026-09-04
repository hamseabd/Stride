import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from strands import tool
from aws_lambda_powertools import Logger

from shared.db import get_table, set_onboarded
from shared.models import Project, WorkCycle, Task, Checkin, Blocker, Velocity, UserPattern, Habit
from shared.tenant import enforce_user

logger = Logger()

VALID_ESTIMATES = {"S": 2, "M": 5, "L": 8, "XL": 13}
VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}
VALID_PREFERENCES = {"timezone", "checkin_time", "evening_time", "planning_day", "name"}


# ---------------------------------------------------------------------------
# Date resolution
# ---------------------------------------------------------------------------

# Patterns: "in 3 months", "3 months", "in 2 weeks", "6 weeks", "in 1 year"
_RELATIVE_RE = re.compile(
    r"(?:in\s+)?(\d+)\s+(day|week|month|year)s?(?:\s+from\s+(?:now|today))?",
    re.IGNORECASE,
)

# Named phrases → (month, day) or special keys
_NAMED_DATES = {
    "end of year": (12, 31),
    "end of the year": (12, 31),
    "new year": (1, 1),  # next year
    "end of q1": (3, 31),
    "end of q2": (6, 30),
    "end of q3": (9, 30),
    "end of q4": (12, 31),
}

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last day of a given month."""
    import calendar
    return calendar.monthrange(year, month)[1]


@tool
def resolve_date(expression: str) -> dict:
    """
    Convert a natural language date expression into YYYY-MM-DD format.

    ALWAYS call this tool when a user gives a date that is not already in YYYY-MM-DD format.
    Examples: "in 3 months", "end of year", "by June", "next March", "6 weeks from now",
    "in 2 weeks", "by December", "end of Q2".

    Do NOT try to calculate dates yourself — always use this tool.

    Params:
      expression: The user's date expression (e.g. "in 3 months", "end of year", "by June").

    Returns on success:
      {"date": "YYYY-MM-DD", "interpreted_as": str}

    Returns on error:
      {"error": str}
    """
    try:
        text = expression.strip().lower()
        today = date.today()

        # 1. Already YYYY-MM-DD?
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            return {"date": text, "interpreted_as": text}

        # 2. Named phrases: "end of year", "end of Q2", etc.
        for phrase, (month, day) in _NAMED_DATES.items():
            if phrase in text:
                year = today.year
                target = date(year, month, day)
                if target <= today:
                    target = date(year + 1, month, day)
                return {"date": target.isoformat(), "interpreted_as": f"{phrase} → {target.isoformat()}"}

        # 3. Relative: "in 3 months", "2 weeks", "1 year"
        m = _RELATIVE_RE.search(text)
        if m:
            amount = int(m.group(1))
            unit = m.group(2).lower()
            if unit == "day":
                target = today + timedelta(days=amount)
            elif unit == "week":
                target = today + timedelta(weeks=amount)
            elif unit == "month":
                new_month = today.month + amount
                new_year = today.year + (new_month - 1) // 12
                new_month = ((new_month - 1) % 12) + 1
                new_day = min(today.day, _last_day_of_month(new_year, new_month))
                target = date(new_year, new_month, new_day)
            elif unit == "year":
                target = date(today.year + amount, today.month, today.day)
            else:
                return {"error": f"Unknown unit: {unit}"}
            return {"date": target.isoformat(), "interpreted_as": f"{amount} {unit}(s) from today → {target.isoformat()}"}

        # 4. Month name: "by June", "next March", "in September"
        for name, month_num in _MONTH_NAMES.items():
            if name in text:
                year = today.year
                # Last day of that month
                day = _last_day_of_month(year, month_num)
                target = date(year, month_num, day)
                if target <= today:
                    year += 1
                    day = _last_day_of_month(year, month_num)
                    target = date(year, month_num, day)
                return {"date": target.isoformat(), "interpreted_as": f"end of {name.title()} {year} → {target.isoformat()}"}

        # 5. "tomorrow"
        if "tomorrow" in text:
            target = today + timedelta(days=1)
            return {"date": target.isoformat(), "interpreted_as": f"tomorrow → {target.isoformat()}"}

        # 6. "next week" / "next month"
        if "next week" in text:
            target = today + timedelta(weeks=1)
            return {"date": target.isoformat(), "interpreted_as": f"next week → {target.isoformat()}"}
        if "next month" in text:
            new_month = today.month + 1
            new_year = today.year + (new_month - 1) // 12
            new_month = ((new_month - 1) % 12) + 1
            day = _last_day_of_month(new_year, new_month)
            target = date(new_year, new_month, day)
            return {"date": target.isoformat(), "interpreted_as": f"end of next month → {target.isoformat()}"}

        return {"error": f"Could not interpret '{expression}'. Ask the user for a specific date or timeframe like 'in 3 months' or 'by June'."}
    except Exception as e:
        logger.exception("resolve_date failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@tool
def create_project(user_id: str, name: str, description: str, target_date: str = "") -> dict:
    """
    Create a new project (goal) for a user and persist it to DynamoDB.

    Params:
      user_id: The user who owns this project (required).
      name: Short project name — this is the user's goal (required).
      description: What the project is about (optional, can be empty).
      target_date: When the user wants to achieve this goal, in YYYY-MM-DD format.
                   If the user gives a relative date (e.g. "in 3 months", "by June",
                   "end of year"), call resolve_date FIRST to get the YYYY-MM-DD value,
                   then pass it here. Must be today or later — past dates are rejected.
                   Empty string if the goal is ongoing with no deadline.

    Returns on success:
      {"project_id": str, "name": str, "target_date": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        if not user_id or not name:
            return {"error": "user_id and name are required"}

        if target_date:
            try:
                parsed = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                return {"error": f"target_date must be YYYY-MM-DD format, got: {target_date}"}
            if parsed < date.today():
                return {"error": f"target_date is in the past ({target_date}). Use a future date."}

        project = Project(user_id=user_id, name=name, description=description, target_date=target_date)
        item = project.model_dump()
        item["pk"] = f"USER#{user_id}"
        item["sk"] = f"PROJECT#{project.project_id}"
        item["gsi1pk"] = f"PROJECT#{project.project_id}"
        item["gsi1sk"] = "#METADATA"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Project created", project_id=project.project_id, user_id=user_id)
        return {"project_id": project.project_id, "name": project.name, "target_date": project.target_date, "created_at": project.created_at}
    except Exception as e:
        logger.exception("create_project failed")
        return {"error": str(e)}


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
                   If relative, call resolve_date first. Must be today or later.

    Returns on success:
      {"project_id": str, "updated_fields": list}

    Returns on error:
      {"error": str}
    """
    try:
        if not project_id:
            return {"error": "project_id is required"}

        if target_date:
            try:
                parsed = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                return {"error": f"target_date must be YYYY-MM-DD format, got: {target_date}"}
            if parsed < date.today():
                return {"error": f"target_date is in the past ({target_date}). Use a future date."}

        table = get_table()

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


@tool
def archive_project(project_id: str) -> dict:
    """
    Archive a project (goal). The project is hidden from the user's active
    and backlog lists but kept in the database for pattern analysis.

    Use this when a user says they want to drop, remove, delete, or cancel a goal.
    Do NOT actually delete the data — archiving preserves history.

    Params:
      project_id: The project UUID to archive (required).

    Returns on success:
      {"project_id": str, "archived": true}

    Returns on error:
      {"error": str}
    """
    try:
        if not project_id:
            return {"error": "project_id is required"}

        table = get_table()

        # Look up project via GSI to get its PK/SK
        resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"PROJECT#{project_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        items = resp.get("Items", [])
        if not items:
            return {"error": f"Project {project_id} not found"}

        item = items[0]
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET archived = :t, archived_at = :now",
            ExpressionAttributeValues={":t": True, ":now": now},
        )

        logger.info("Project archived", project_id=project_id, user_id=item["pk"])
        return {"project_id": project_id, "archived": True}
    except Exception as e:
        logger.exception("archive_project failed")
        return {"error": str(e)}


@tool
def create_work_cycle(
    project_id: str, name: str, goal: str, start_date: str, end_date: str
) -> dict:
    """
    Create a new work cycle (week or planning period) for a project.

    Params:
      project_id: The project UUID this cycle belongs to (required).
      name: Short cycle name, e.g. "Week 1" (required).
      goal: What the user wants to accomplish this cycle (required).
      start_date: Start date in YYYY-MM-DD format (required).
      end_date: End date in YYYY-MM-DD format (required).

    Returns on success:
      {"cycle_id": str, "name": str, "goal": str, "start_date": str, "end_date": str}

    Returns on error:
      {"error": str}  — e.g. project not found, missing params, invalid date format.
    """
    try:
        if not all([project_id, name, goal, start_date, end_date]):
            return {"error": "All params are required: project_id, name, goal, start_date, end_date"}

        # Validate date format
        for label, val in [("start_date", start_date), ("end_date", end_date)]:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                return {"error": f"{label} must be in YYYY-MM-DD format, got: {val}"}

        table = get_table()

        # Validate project exists via GSI1
        resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"PROJECT#{project_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        if not resp.get("Items"):
            return {"error": f"Project {project_id} not found"}

        cycle = WorkCycle(
            project_id=project_id,
            name=name,
            goal=goal,
            start_date=start_date,
            end_date=end_date,
        )
        item = cycle.model_dump()
        item["pk"] = f"PROJECT#{project_id}"
        item["sk"] = f"CYCLE#{cycle.cycle_id}"
        item["gsi1pk"] = f"CYCLE#{cycle.cycle_id}"
        item["gsi1sk"] = "#METADATA"

        table.put_item(Item=item)
        logger.info("Work cycle created", cycle_id=cycle.cycle_id, project_id=project_id)
        return {
            "cycle_id": cycle.cycle_id,
            "name": cycle.name,
            "goal": cycle.goal,
            "start_date": cycle.start_date,
            "end_date": cycle.end_date,
        }
    except Exception as e:
        logger.exception("create_work_cycle failed")
        return {"error": str(e)}


@tool
def list_active_projects(user_id: str) -> dict:
    """
    List all projects for a user, including their active work cycle (if any).

    Params:
      user_id: The user UUID to look up.

    Returns on success:
      {"projects": [{"project_id": str, "name": str, "description": str, "target_date": str, "active_cycle": dict | null}]}
      An empty list is a valid success response — it means the user has no projects yet.

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        table = get_table()

        # Query all projects for this user
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("PROJECT#"),
        )
        project_items = resp.get("Items", [])

        projects = []
        for p in project_items:
            # Skip archived projects
            if p.get("archived"):
                continue

            project_id = p.get("project_id")
            active_cycle = None

            # Find active cycle for this project
            cycles_resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"PROJECT#{project_id}") & Key("sk").begins_with("CYCLE#"),
            )
            for c in cycles_resp.get("Items", []):
                if c.get("status") == "active":
                    active_cycle = {
                        "cycle_id": c.get("cycle_id"),
                        "name": c.get("name"),
                        "goal": c.get("goal"),
                        "start_date": c.get("start_date"),
                        "end_date": c.get("end_date"),
                    }
                    break

            projects.append({
                "project_id": project_id,
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "target_date": p.get("target_date", ""),
                "active_cycle": active_cycle,
            })

        logger.info("Active projects listed", user_id=user_id, count=len(projects))
        return {"projects": projects}
    except Exception as e:
        logger.exception("list_active_projects failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@tool
def create_task(title: str, description: str, estimate: str, cycle_id: str) -> dict:
    """
    Create a new task and persist it to DynamoDB under the given work cycle.

    Params:
      title: Short task title (required).
      description: Details or acceptance criteria.
      estimate: Size estimate. Must be one of: S (a few hours), M (a day or two),
                L (most of the week), XL (more than a week — flags as scope risk).
      cycle_id: The work cycle this task belongs to.

    Returns on success:
      {"task_id": str, "estimate": int, "estimate_label": str, "status": "todo", "created_at": str}

    Returns on error:
      {"error": str}  — e.g. if estimate is not S/M/L/XL.
    """
    try:
        estimate = estimate.upper()
        if estimate not in VALID_ESTIMATES:
            return {"error": f"Invalid estimate '{estimate}'. Must be one of: S, M, L, XL"}

        points = VALID_ESTIMATES[estimate]
        task = Task(
            cycle_id=cycle_id,
            title=title,
            description=description,
            estimate=points,
            estimate_label=estimate,
        )
        item = task.model_dump()
        item["pk"] = f"CYCLE#{cycle_id}"
        item["sk"] = f"TASK#{task.task_id}"
        item["gsi1pk"] = f"TASK#{task.task_id}"
        item["gsi1sk"] = f"STATUS#todo"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Task created", task_id=task.task_id, cycle_id=cycle_id, estimate=estimate)
        return {
            "task_id": task.task_id,
            "estimate": points,
            "estimate_label": estimate,
            "status": "todo",
            "created_at": task.created_at,
        }
    except Exception as e:
        logger.exception("create_task failed")
        return {"error": str(e)}


@tool
def update_task_status(task_id: str, status: str) -> dict:
    """
    Update the status of an existing task.

    Params:
      task_id: The UUID of the task to update.
      status: New status. Must be one of: todo, in_progress, done, blocked.

    Returns on success:
      {"task_id": str, "previous_status": str, "status": str, "updated_at": str}

    Returns on error:
      {"error": str}  — e.g. task not found, invalid status.
    """
    try:
        if status not in VALID_STATUSES:
            return {"error": f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}"}

        table = get_table()

        # Look up the task's base PK/SK via GSI1
        resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"TASK#{task_id}"),
        )
        items = resp.get("Items", [])
        if not items:
            return {"error": f"Task {task_id} not found"}

        item = items[0]
        pk = item["pk"]
        sk = item["sk"]
        previous_status = item.get("status", "todo")
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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
        logger.info("Task status updated", task_id=task_id, status=status)
        return {
            "task_id": task_id,
            "previous_status": previous_status,
            "status": status,
            "updated_at": updated_at,
        }
    except Exception as e:
        logger.exception("update_task_status failed")
        return {"error": str(e)}


@tool
def get_cycle_data(cycle_id: str) -> dict:
    """
    Retrieve work cycle metadata and all its tasks from DynamoDB.

    Params:
      cycle_id: The work cycle UUID to look up.

    Returns on success:
      {"cycle": dict, "tasks": list[dict], "task_count": int}
      cycle contains cycle metadata; tasks is the list of task items.

    Returns on error:
      {"error": str}
    """
    try:
        table = get_table()

        # Get cycle metadata via GSI1
        cycle_resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"CYCLE#{cycle_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        cycle_items = cycle_resp.get("Items", [])
        cycle = cycle_items[0] if cycle_items else {}

        # Get all tasks for this cycle from base table
        tasks_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"CYCLE#{cycle_id}") & Key("sk").begins_with("TASK#"),
        )
        tasks = tasks_resp.get("Items", [])

        logger.info("Cycle data retrieved", cycle_id=cycle_id, task_count=len(tasks))
        return {"cycle": cycle, "tasks": tasks, "task_count": len(tasks)}
    except Exception as e:
        logger.exception("get_cycle_data failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Check-ins and blockers
# ---------------------------------------------------------------------------

@tool
def create_checkin(user_id: str, did: str, doing: str, blocked: str) -> dict:
    """
    Record a daily check-in for a user and persist it to DynamoDB.

    Params:
      user_id: The user UUID submitting the check-in.
      did: What they accomplished since the last check-in.
      doing: What they plan to work on today.
      blocked: Anything stopping them (empty string if nothing).

    Returns on success:
      {"checkin_id": str, "user_id": str, "date": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        checkin = Checkin(user_id=user_id, did=did, doing=doing, blocked=blocked)
        item = checkin.model_dump()
        item["pk"] = f"USER#{user_id}"
        item["sk"] = f"CHECKIN#{checkin.date}#{checkin.checkin_id}"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Check-in created", checkin_id=checkin.checkin_id, user_id=user_id)
        return {
            "checkin_id": checkin.checkin_id,
            "user_id": user_id,
            "date": checkin.date,
            "created_at": checkin.created_at,
        }
    except Exception as e:
        logger.exception("create_checkin failed")
        return {"error": str(e)}


@tool
def flag_blocker(task_id: str, description: str, category: str) -> dict:
    """
    Flag a blocker for a given task and persist it to DynamoDB.

    Params:
      task_id: The task UUID that is blocked.
      description: What is blocking progress.
      category: Blocker category. Must be one of: external, scope, capacity, process.
                Use "external" for dependencies on other people or services,
                "scope" for the task being bigger than expected,
                "capacity" for not having enough time,
                "process" for workflow or tooling issues.

    Returns on success:
      {"blocker_id": str, "task_id": str, "category": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
    try:
        valid_categories = {"external", "scope", "capacity", "process"}
        if category not in valid_categories:
            return {"error": f"Invalid category '{category}'. Must be one of: {sorted(valid_categories)}"}

        blocker = Blocker(task_id=task_id, description=description, category=category)
        item = blocker.model_dump()
        item["pk"] = f"TASK#{task_id}"
        item["sk"] = f"BLOCKER#{blocker.blocker_id}"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Blocker flagged", blocker_id=blocker.blocker_id, task_id=task_id)
        return {"blocker_id": blocker.blocker_id, "task_id": task_id, "category": blocker.category, "created_at": blocker.created_at}
    except Exception as e:
        logger.exception("flag_blocker failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Pace history and patterns
# ---------------------------------------------------------------------------

@tool
def get_pace_history(project_id: str, num_cycles: int) -> dict:
    """
    Retrieve recent pace records for a project and compute statistics.

    Params:
      project_id: The project UUID.
      num_cycles: How many recent work cycles to include (e.g. 3).

    Returns on success:
      {
        "project_id": str,
        "cycle_records": list[dict],        # up to num_cycles most recent
        "average_pace": float,              # avg delivered_points per cycle
        "average_completion_rate": float,   # avg delivered/planned ratio
        "trend": str                        # "improving", "declining", or "stable"
      }

    Returns on error:
      {"error": str}
    """
    try:
        table = get_table()

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"PROJECT#{project_id}") & Key("sk").begins_with("VELOCITY#"),
            ScanIndexForward=False,
            Limit=num_cycles,
        )
        records = resp.get("Items", [])

        if not records:
            return {
                "project_id": project_id,
                "cycle_records": [],
                "average_pace": 0.0,
                "average_completion_rate": 0.0,
                "trend": "stable",
            }

        delivered = [float(r.get("delivered_points", 0)) for r in records]
        planned = [float(r.get("planned_points", 0)) for r in records]

        avg_pace = sum(delivered) / len(delivered) if delivered else 0.0
        rates = [d / p if p else 0.0 for d, p in zip(delivered, planned)]
        avg_rate = sum(rates) / len(rates) if rates else 0.0

        # Trend: compare older half vs newer half (records are newest-first)
        trend = "stable"
        if len(delivered) >= 2:
            mid = len(delivered) // 2
            older_avg = sum(delivered[mid:]) / len(delivered[mid:])
            newer_avg = sum(delivered[:mid]) / len(delivered[:mid])
            if newer_avg > older_avg * 1.1:
                trend = "improving"
            elif newer_avg < older_avg * 0.9:
                trend = "declining"

        logger.info("Pace history retrieved", project_id=project_id, cycle_count=len(records))
        return {
            "project_id": project_id,
            "cycle_records": records,
            "average_pace": round(avg_pace, 2),
            "average_completion_rate": round(avg_rate, 2),
            "trend": trend,
        }
    except Exception as e:
        logger.exception("get_pace_history failed")
        return {"error": str(e)}


@tool
def record_velocity(
    project_id: str,
    cycle_id: str,
    planned_points: int,
    delivered_points: int,
    cycle_name: str,
) -> dict:
    """
    Record the pace (velocity) result for a completed work cycle.
    Call this at the end of a weekly review after tallying planned vs delivered points.

    Params:
      project_id:       The project UUID.
      cycle_id:         The completed work cycle UUID.
      planned_points:   Total points planned at the start of the cycle.
      delivered_points: Total points actually delivered (tasks marked done).
      cycle_name:       Human-readable cycle name, e.g. "Week 1".

    Returns on success:
      {"project_id": str, "cycle_id": str, "planned_points": int,
       "delivered_points": int, "recorded_at": str}

    Returns on error:
      {"error": str}
    """
    try:
        if not project_id or not cycle_id:
            return {"error": "project_id and cycle_id are required"}
        if planned_points < 0 or delivered_points < 0:
            return {"error": "points must be non-negative"}

        table = get_table()

        # Compute active project count for context-switching data
        project_resp = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"PROJECT#{project_id}") & Key("gsi1sk").eq("#METADATA"),
        )
        project_item = project_resp.get("Items", [{}])[0]
        owner_id = project_item.get("user_id", "")
        active_count = 0
        if owner_id:
            proj_resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"USER#{owner_id}") & Key("sk").begins_with("PROJECT#"),
            )
            active_count = len(proj_resp.get("Items", []))

        velocity = Velocity(
            project_id=project_id,
            cycle_id=cycle_id,
            planned_points=planned_points,
            delivered_points=delivered_points,
            cycle_name=cycle_name,
            active_project_count=active_count,
        )
        item = velocity.model_dump()
        item["pk"] = f"PROJECT#{project_id}"
        item["sk"] = f"VELOCITY#{cycle_id}"

        table.put_item(Item=item)
        logger.info("Velocity recorded", project_id=project_id, cycle_id=cycle_id)
        return {
            "project_id": project_id,
            "cycle_id": cycle_id,
            "planned_points": planned_points,
            "delivered_points": delivered_points,
            "recorded_at": velocity.recorded_at,
        }
    except Exception as e:
        logger.exception("record_velocity failed")
        return {"error": str(e)}


@tool
def update_user_patterns(
    user_id: str,
    delivered_points: int,
    planned_points: int,
    new_blockers: list,
) -> dict:
    """
    Update the aggregated pattern record for a user after a cycle review.
    Recalculates rolling averages for pace and completion rate.
    Call this at the end of every weekly review.

    Params:
      user_id:          The user UUID.
      delivered_points: Points delivered this cycle.
      planned_points:   Points planned this cycle (must be > 0 to avoid division by zero).
      new_blockers:     List of blocker description strings from this cycle (can be empty).

    Returns on success:
      {"user_id": str, "avg_pace": float, "avg_completion_rate": float,
       "cycle_count": int, "updated_at": str}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        if not user_id:
            return {"error": "user_id is required"}

        table = get_table()
        resp  = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"})
        existing = resp.get("Item")

        old_count = int(existing.get("cycle_count", 0)) if existing else 0
        old_pace  = float(existing.get("avg_pace", 0.0)) if existing else 0.0
        old_rate  = float(existing.get("avg_completion_rate", 0.0)) if existing else 0.0
        old_blockers = existing.get("common_blockers", []) if existing else []
        existing_tone = existing.get("preferred_tone", "balanced") if existing else "balanced"

        new_count = old_count + 1
        new_pace  = ((old_pace * old_count) + delivered_points) / new_count
        completion = (delivered_points / planned_points) if planned_points > 0 else 0.0
        new_rate  = ((old_rate * old_count) + completion) / new_count

        merged_blockers = list(set(old_blockers + (new_blockers or [])))[:20]

        pattern = UserPattern(
            user_id=user_id,
            avg_pace=round(new_pace, 2),
            avg_completion_rate=round(new_rate, 2),
            common_blockers=merged_blockers,
            cycle_count=new_count,
            preferred_tone=existing_tone,
        )
        item = pattern.model_dump()
        item["pk"] = f"USER#{user_id}"
        item["sk"] = "PATTERN#AGGREGATE"
        # DynamoDB rejects Python float — convert to Decimal
        item["avg_pace"] = Decimal(str(item["avg_pace"]))
        item["avg_completion_rate"] = Decimal(str(item["avg_completion_rate"]))

        table.put_item(Item=item)
        logger.info("User patterns updated", user_id=user_id, cycle_count=new_count)
        return {
            "user_id": user_id,
            "avg_pace": pattern.avg_pace,
            "avg_completion_rate": pattern.avg_completion_rate,
            "cycle_count": new_count,
            "updated_at": pattern.updated_at,
        }
    except Exception as e:
        logger.exception("update_user_patterns failed")
        return {"error": str(e)}


@tool
def complete_onboarding(user_id: str) -> dict:
    """
    Mark a user as fully onboarded. Call this at the end of a successful setup
    session — after their first project, work cycle, and at least one task have
    been created.

    Params:
      user_id: The user UUID to mark as onboarded.

    Returns on success:
      {"user_id": str, "onboarded": true}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        if not user_id:
            return {"error": "user_id is required"}
        ok = set_onboarded(user_id)
        if ok:
            logger.info("Onboarding completed", user_id=user_id)
            return {"user_id": user_id, "onboarded": True}
        return {"error": "failed to mark user as onboarded"}
    except Exception as e:
        logger.exception("complete_onboarding failed")
        return {"error": str(e)}


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
    user_id = enforce_user(user_id)
    try:
        from shared.db import store_feedback
        store_feedback(user_id, feedback, source="agent")
        logger.info("Feedback submitted via tool", user_id=user_id)
        return {"stored": True}
    except Exception as e:
        logger.exception("submit_feedback failed")
        return {"error": str(e)}


@tool
def get_user_patterns(user_id: str) -> dict:
    """
    Retrieve the aggregated pattern record for a user.
    Returns empty-state defaults if no record exists yet.

    Params:
      user_id: The user UUID to look up.

    Returns on success (record found):
      {"user_id": str, "avg_pace": float, "avg_completion_rate": float,
       "common_blockers": list, "cycle_count": int, "updated_at": str, "found": true}

    Returns on success (no record yet):
      {"user_id": str, "avg_pace": 0.0, "avg_completion_rate": 0.0,
       "common_blockers": [], "cycle_count": 0, "updated_at": null, "found": false}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        table = get_table()
        resp = table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"}
        )
        item = resp.get("Item")
        if item:
            logger.info("User patterns found", user_id=user_id)
            return {
                "user_id": user_id,
                "avg_pace": float(item.get("avg_pace", 0.0)),
                "avg_completion_rate": float(item.get("avg_completion_rate", 0.0)),
                "common_blockers": item.get("common_blockers", []),
                "cycle_count": int(item.get("cycle_count", 0)),
                "updated_at": item.get("updated_at"),
                "found": True,
            }
        else:
            logger.info("No user patterns found, returning defaults", user_id=user_id)
            return {
                "user_id": user_id,
                "avg_pace": 0.0,
                "avg_completion_rate": 0.0,
                "common_blockers": [],
                "cycle_count": 0,
                "updated_at": None,
                "found": False,
            }
    except Exception as e:
        logger.exception("get_user_patterns failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

@tool
def set_user_preference(user_id: str, preference: str, value: str) -> dict:
    """
    Update a user preference. Call this when a user expresses a preference
    like "I'm in California" or "I prefer evening check-ins."

    Params:
      user_id: The user whose preference to update.
      preference: Must be one of: name, timezone, checkin_time, evening_time, planning_day.
      value: The new value. Format depends on preference:
        - name: The user's preferred name (e.g. "John")
        - timezone: IANA timezone string (e.g. "America/Los_Angeles")
        - checkin_time: HH:MM in 24h format (e.g. "09:00")
        - evening_time: HH:MM in 24h format (e.g. "18:00")
        - planning_day: integer 1-7 where 1=Monday, 7=Sunday

    Returns on success:
      {"user_id": str, "preference": str, "value": str, "updated": true}

    Returns on error:
      {"error": str}
    """
    user_id = enforce_user(user_id)
    try:
        if preference not in VALID_PREFERENCES:
            return {"error": f"Invalid preference '{preference}'. Must be one of: {sorted(VALID_PREFERENCES)}"}

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
                value = day
            except (ValueError, TypeError):
                return {"error": f"planning_day must be 1-7 (1=Monday), got: {value}"}

        table = get_table()
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": "#METADATA"},
            UpdateExpression="SET #pref = :val",
            ExpressionAttributeNames={"#pref": preference},
            ExpressionAttributeValues={":val": value},
        )
        logger.info("User preference updated", user_id=user_id, preference=preference)
        return {"user_id": user_id, "preference": preference, "value": str(value), "updated": True}
    except Exception as e:
        logger.exception("set_user_preference failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

VALID_FREQUENCIES = {"daily", "weekdays", "3x_week", "weekly"}


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
        if gap == 1:
            return True
        if gap == 3 and last.isoweekday() == 5:  # Friday → Monday
            return True
        return False
    elif frequency == "weekly":
        return gap <= 7
    elif frequency == "3x_week":
        return gap <= 7
    return gap == 1


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
    user_id = enforce_user(user_id)
    try:
        if frequency not in VALID_FREQUENCIES:
            return {"error": f"Invalid frequency '{frequency}'. Must be one of: {sorted(VALID_FREQUENCIES)}"}

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
    user_id = enforce_user(user_id)
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
            return {
                "habit_id": habit_id,
                "date": today,
                "current_streak": int(item.get("streak_at_completion", 0)),
                "longest_streak": int(item.get("longest_at_completion", 0)),
                "already_done": True,
            }

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
            current_streak = 1

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
    user_id = enforce_user(user_id)
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

import os
from datetime import datetime
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from strands import tool
from aws_lambda_powertools import Logger

from shared.db import get_table, set_onboarded
from shared.models import Project, WorkCycle, Task, Checkin, Blocker, Velocity, UserPattern

logger = Logger()

VALID_ESTIMATES = {"S": 2, "M": 5, "L": 8, "XL": 13}
VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@tool
def create_project(user_id: str, name: str, description: str) -> dict:
    """
    Create a new project for a user and persist it to DynamoDB.

    Params:
      user_id: The user UUID who owns this project (required).
      name: Short project name (required).
      description: What the project is about (optional, can be empty).

    Returns on success:
      {"project_id": str, "name": str, "created_at": str}

    Returns on error:
      {"error": str}  — e.g. if user_id or name is missing.
    """
    try:
        if not user_id or not name:
            return {"error": "user_id and name are required"}

        project = Project(user_id=user_id, name=name, description=description)
        item = project.model_dump()
        item["pk"] = f"USER#{user_id}"
        item["sk"] = f"PROJECT#{project.project_id}"
        item["gsi1pk"] = f"PROJECT#{project.project_id}"
        item["gsi1sk"] = "#METADATA"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Project created", project_id=project.project_id, user_id=user_id)
        return {"project_id": project.project_id, "name": project.name, "created_at": project.created_at}
    except Exception as e:
        logger.exception("create_project failed")
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
      {"projects": [{"project_id": str, "name": str, "description": str, "active_cycle": dict | null}]}
      An empty list is a valid success response — it means the user has no projects yet.

    Returns on error:
      {"error": str}
    """
    try:
        table = get_table()

        # Query all projects for this user
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("PROJECT#"),
        )
        project_items = resp.get("Items", [])

        projects = []
        for p in project_items:
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
        updated_at = datetime.utcnow().isoformat() + "Z"

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
def flag_blocker(task_id: str, description: str) -> dict:
    """
    Flag a blocker for a given task and persist it to DynamoDB.

    Params:
      task_id: The task UUID that is blocked.
      description: What is blocking progress.

    Returns on success:
      {"blocker_id": str, "task_id": str, "created_at": str}

    Returns on error:
      {"error": str}
    """
    try:
        blocker = Blocker(task_id=task_id, description=description)
        item = blocker.model_dump()
        item["pk"] = f"TASK#{task_id}"
        item["sk"] = f"BLOCKER#{blocker.blocker_id}"

        table = get_table()
        table.put_item(Item=item)
        logger.info("Blocker flagged", blocker_id=blocker.blocker_id, task_id=task_id)
        return {"blocker_id": blocker.blocker_id, "task_id": task_id, "created_at": blocker.created_at}
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

        velocity = Velocity(
            project_id=project_id,
            cycle_id=cycle_id,
            planned_points=planned_points,
            delivered_points=delivered_points,
            cycle_name=cycle_name,
        )
        item = velocity.model_dump()
        item["pk"] = f"PROJECT#{project_id}"
        item["sk"] = f"VELOCITY#{cycle_id}"

        get_table().put_item(Item=item)
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

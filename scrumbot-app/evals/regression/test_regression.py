"""Regression tests for known production bugs. Moto-based, no LLM calls.

The `ddb` fixture and env setup live in evals/conftest.py so every eval test
shares one schema definition (no drift between copies).
"""
from datetime import date, timedelta
from decimal import Decimal

# Relative dates so seeded cycles never fall into the past as the calendar moves.
_CYCLE_START = (date.today() + timedelta(days=1)).isoformat()
_CYCLE_END = (date.today() + timedelta(days=7)).isoformat()


def _seed_user(ddb, user_id):
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": "#METADATA",
        "phone": user_id, "onboarded": True,
    })


def _seed_project_and_cycle(ddb, user_id, project_id, cycle_id):
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": f"PROJECT#{project_id}",
        "gsi1pk": f"PROJECT#{project_id}", "gsi1sk": "#METADATA",
        # user_id is on every real project record; record_velocity reads it to count
        # active projects, so omitting it silently zeroes active_project_count.
        "name": "Regression Project", "project_id": project_id, "user_id": user_id,
    })
    ddb.put_item(Item={
        "pk": f"PROJECT#{project_id}", "sk": f"CYCLE#{cycle_id}",
        "gsi1pk": f"CYCLE#{cycle_id}", "gsi1sk": "#METADATA",
        "cycle_id": cycle_id, "project_id": project_id,
        "start_date": _CYCLE_START, "end_date": _CYCLE_END,
        "planned_points": 8,
    })


def test_bug_001_update_user_patterns_preserves_tone(ddb):
    """
    BUG-001: update_user_patterns() must not reset preferred_tone to 'balanced'
    when the user has explicitly set it to 'direct' or 'encouraging'.
    Fixed pre-v1.1.
    """
    from shared.tools import record_velocity, update_user_patterns

    user_id = "+15550000001"
    project_id = "proj-bug001"
    cycle_id = "cycle-bug001"

    # Seed pattern record with preferred_tone explicitly set to "direct"
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE",
        "preferred_tone": "direct",
        "avg_pace": Decimal("0"),
        "avg_completion_rate": Decimal("0"),
        "cycle_count": 0,
    })
    _seed_user(ddb, user_id)
    _seed_project_and_cycle(ddb, user_id, project_id, cycle_id)

    record_velocity(
        cycle_id=cycle_id, project_id=project_id,
        planned_points=8, delivered_points=5, cycle_name="Week 1",
    )
    update_user_patterns(
        user_id=user_id, delivered_points=5, planned_points=8, new_blockers=[],
    )

    item = ddb.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"}
    ).get("Item", {})
    assert item.get("preferred_tone") == "direct", (
        f"BUG-001 regression: preferred_tone was reset to {item.get('preferred_tone')!r}"
    )


def test_bug_001_boundary_new_user_defaults_to_balanced(ddb):
    """
    BUG-001 boundary: a user with NO prior pattern record must default to
    'balanced'. This pins the other side of the fix — without it, the tone
    could be hardcoded to 'direct' and the primary test would still pass.
    """
    from shared.tools import update_user_patterns

    user_id = "+15550000002"

    # No PATTERN#AGGREGATE seeded — first review for this user. update_user_patterns
    # only reads/writes PATTERN#AGGREGATE, so no project/cycle seed is needed here.
    _seed_user(ddb, user_id)

    update_user_patterns(
        user_id=user_id, delivered_points=5, planned_points=8, new_blockers=[],
    )

    item = ddb.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"}
    ).get("Item", {})
    assert item.get("preferred_tone") == "balanced", (
        f"new user should default to 'balanced', got {item.get('preferred_tone')!r}"
    )


def test_bug_002_tool_ignores_model_supplied_user_id(ddb):
    """
    BUG-002: tools trusted the user_id the model passed. The handler only told
    the model the current id in the system prompt, so an injected SMS could
    point the agent at another user's records. Fixed 2026-09 by binding the
    authenticated user server-side; tools act on the bound id.
    """
    from shared.tenant import bind_user
    from shared.tools import create_project, list_active_projects

    victim = "+15550000021"
    attacker = "+15550000022"
    _seed_user(ddb, victim)
    _seed_user(ddb, attacker)

    with bind_user(attacker):
        create_project(user_id=victim, name="Planted", description="", target_date="")

    assert list_active_projects(user_id=victim)["projects"] == [], (
        "BUG-002 regression: a project was written under a user the model named, not the bound user"
    )
    assert [p["name"] for p in list_active_projects(user_id=attacker)["projects"]] == ["Planted"]


def test_bug_003_context_exposes_ids_the_tools_need(ddb):
    """
    BUG-003: the pre-loaded context listed projects and tasks by name only. With a short
    history the model guessed ids — it passed a project name as project_id and fabricated
    task ids — and then reported success on calls that had failed. Fixed 2026-09 (v2.3):
    every project and task line carries its id and the context says never to guess one.
    """
    from datetime import date, timedelta
    from functions.sms.handler import _build_user_context
    from shared.tools import create_project, create_work_cycle, create_task

    user_id = "+15550000031"
    _seed_user(ddb, user_id)
    project_id = create_project(user_id=user_id, name="Extension", description="", target_date="")["project_id"]
    cycle_id = create_work_cycle(
        project_id=project_id, name="Week 1", goal="Ship",
        start_date=(date.today() + timedelta(days=1)).isoformat(),
        end_date=(date.today() + timedelta(days=7)).isoformat(),
    )["cycle_id"]
    task_id = create_task(title="Blocklist UI", description="", estimate="M", cycle_id=cycle_id)["task_id"]

    ctx = _build_user_context(user_id, {"planning_day": 1, "timezone": "America/New_York"}, is_new_user=False)
    assert f"(id {project_id})" in ctx, "BUG-003 regression: project id missing from context"
    assert f"(id {task_id})" in ctx, "BUG-003 regression: task id missing from context"

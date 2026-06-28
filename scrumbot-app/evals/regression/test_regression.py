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

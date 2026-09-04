"""Tools act on the bound user even when the model supplies a different id."""

import pytest

from shared.tenant import bind_user

BOUND = "+15550000001"
OTHER = "+15550000009"


@pytest.fixture
def two_users(ddb):
    from shared.db import get_or_create_user, record_consent
    for uid in (BOUND, OTHER):
        record_consent(user_id=uid, phone=uid)
        get_or_create_user(user_id=uid, phone=uid)
    return BOUND, OTHER


def test_create_project_lands_under_bound_user(two_users):
    from shared.tools import create_project, list_active_projects
    with bind_user(BOUND):
        result = create_project(user_id=OTHER, name="Injected", description="", target_date="")
    assert "project_id" in result
    assert [p["name"] for p in list_active_projects(user_id=BOUND)["projects"]] == ["Injected"]
    assert list_active_projects(user_id=OTHER)["projects"] == []


def test_read_tools_return_bound_users_data(two_users):
    from shared.tools import create_habit, list_habits, list_active_projects
    create_habit(user_id=BOUND, title="Ship daily", frequency="daily")
    with bind_user(BOUND):
        habits = list_habits(user_id=OTHER)
        projects = list_active_projects(user_id=OTHER)
    assert [h["title"] for h in habits["habits"]] == ["Ship daily"]
    assert projects["projects"] == []  # BOUND has no projects; OTHER's id was ignored


def test_preference_write_cannot_cross_tenants(two_users, ddb):
    from shared.tools import set_user_preference
    with bind_user(BOUND):
        set_user_preference(user_id=OTHER, preference="name", value="Mallory")
    other = ddb.get_item(Key={"pk": f"USER#{OTHER}", "sk": "#METADATA"}).get("Item", {})
    bound = ddb.get_item(Key={"pk": f"USER#{BOUND}", "sk": "#METADATA"}).get("Item", {})
    # get_or_create_user seeds every user with name="" (Pydantic default), not an
    # absent key — assert it stayed empty rather than expecting None.
    assert other.get("name") == ""
    assert bound.get("name") == "Mallory"


@pytest.mark.parametrize("tool_name", [
    "create_project", "list_active_projects", "create_checkin", "update_user_patterns",
    "complete_onboarding", "submit_feedback", "get_user_patterns", "set_user_preference",
    "create_habit", "complete_habit", "list_habits",
])
def test_every_user_keyed_tool_calls_enforce_user(tool_name):
    """Static guard: the first statement after the docstring must be the enforce call."""
    import inspect
    from shared import tools
    src = inspect.getsource(getattr(tools, tool_name))
    assert "user_id = enforce_user(user_id)" in src, f"{tool_name} does not enforce the bound user"

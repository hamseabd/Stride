from decimal import Decimal

from shared.tools import (
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
)


# ---------------------------------------------------------------------------
# Validation (no DynamoDB needed — checks happen before DB calls)
# ---------------------------------------------------------------------------

class TestValidation:
    def test_create_project_missing_user_id(self):
        result = create_project(user_id="", name="Test", description="")
        assert "error" in result

    def test_create_project_missing_name(self):
        result = create_project(user_id="u1", name="", description="")
        assert "error" in result

    def test_create_project_bad_date(self):
        result = create_project(user_id="u1", name="T", description="", target_date="not-a-date")
        assert "YYYY-MM-DD" in result["error"]

    def test_create_task_invalid_estimate(self):
        result = create_task(title="T", description="", estimate="Z", cycle_id="c1")
        assert "Invalid estimate" in result["error"]

    def test_update_task_status_invalid(self):
        result = update_task_status(task_id="t1", status="invalid")
        assert "error" in result

    def test_flag_blocker_invalid_category(self):
        result = flag_blocker(task_id="t1", description="d", category="invalid")
        assert "error" in result

    def test_record_velocity_negative_points(self):
        result = record_velocity(
            project_id="p1", cycle_id="c1",
            planned_points=-1, delivered_points=0, cycle_name="W1",
        )
        assert "error" in result

    def test_record_velocity_missing_ids(self):
        result = record_velocity(
            project_id="", cycle_id="c1",
            planned_points=10, delivered_points=5, cycle_name="W1",
        )
        assert "error" in result

    def test_set_preference_invalid_key(self):
        result = set_user_preference(user_id="u1", preference="color", value="blue")
        assert "error" in result

    def test_set_preference_bad_time(self):
        result = set_user_preference(user_id="u1", preference="checkin_time", value="25:00")
        assert "error" in result

    def test_set_preference_bad_planning_day(self):
        result = set_user_preference(user_id="u1", preference="planning_day", value="8")
        assert "error" in result

    def test_create_habit_invalid_frequency(self):
        result = create_habit(user_id="u1", title="Write", frequency="biweekly")
        assert "error" in result

    def test_update_project_no_fields(self):
        result = update_project(project_id="", name="", description="", target_date="")
        assert "error" in result

    def test_update_project_bad_date(self):
        result = update_project(project_id="p1", target_date="nope")
        assert "YYYY-MM-DD" in result["error"]


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

class TestProjectTools:
    def test_create_project(self, seeded_user):
        result = create_project(user_id=seeded_user, name="Blog", description="My blog")
        assert "project_id" in result
        assert result["name"] == "Blog"
        assert result["target_date"] == ""

    def test_create_project_with_date(self, seeded_user):
        result = create_project(user_id=seeded_user, name="Portfolio", description="", target_date="2026-06-01")
        assert result["target_date"] == "2026-06-01"

    def test_list_active_projects_empty(self, seeded_user):
        result = list_active_projects(user_id=seeded_user)
        assert result["projects"] == []

    def test_list_active_projects_with_project(self, seeded_project):
        user_id, project_id = seeded_project
        result = list_active_projects(user_id=user_id)
        assert len(result["projects"]) == 1
        assert result["projects"][0]["project_id"] == project_id
        assert result["projects"][0]["target_date"] == "2026-06-01"

    def test_update_project_name(self, seeded_project):
        _, project_id = seeded_project
        result = update_project(project_id=project_id, name="New Name")
        assert "name" in result["updated_fields"]

    def test_update_project_not_found(self, ddb):
        result = update_project(project_id="nonexistent", name="X")
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Work Cycle + Task CRUD
# ---------------------------------------------------------------------------

class TestCycleTools:
    def test_create_work_cycle(self, seeded_project):
        _, project_id = seeded_project
        result = create_work_cycle(
            project_id=project_id, name="Week 1", goal="Design",
            start_date="2026-03-02", end_date="2026-03-08",
        )
        assert "cycle_id" in result
        assert result["name"] == "Week 1"

    def test_create_cycle_project_not_found(self, ddb):
        result = create_work_cycle(
            project_id="nonexistent", name="W1", goal="G",
            start_date="2026-03-02", end_date="2026-03-08",
        )
        assert "not found" in result["error"]

    def test_create_cycle_bad_date(self, seeded_project):
        _, project_id = seeded_project
        result = create_work_cycle(
            project_id=project_id, name="W1", goal="G",
            start_date="bad", end_date="2026-03-08",
        )
        assert "YYYY-MM-DD" in result["error"]


class TestTaskTools:
    def test_create_task(self, seeded_cycle):
        _, _, cycle_id = seeded_cycle
        result = create_task(title="Design logo", description="", estimate="S", cycle_id=cycle_id)
        assert "task_id" in result
        assert result["estimate"] == 2
        assert result["estimate_label"] == "S"
        assert result["status"] == "todo"

    def test_update_task_status(self, seeded_task):
        _, _, _, task_id = seeded_task
        result = update_task_status(task_id=task_id, status="done")
        assert result["status"] == "done"
        assert result["previous_status"] == "todo"

    def test_update_task_not_found(self, ddb):
        result = update_task_status(task_id="nonexistent", status="done")
        assert "not found" in result["error"]

    def test_get_cycle_data(self, seeded_task):
        _, _, cycle_id, task_id = seeded_task
        result = get_cycle_data(cycle_id=cycle_id)
        assert result["task_count"] == 1
        assert result["tasks"][0]["task_id"] == task_id


# ---------------------------------------------------------------------------
# Checkin + Blocker
# ---------------------------------------------------------------------------

class TestCheckinTools:
    def test_create_checkin(self, seeded_user):
        result = create_checkin(user_id=seeded_user, did="wireframes", doing="color palette", blocked="")
        assert "checkin_id" in result
        assert result["user_id"] == seeded_user


class TestBlockerTools:
    def test_flag_blocker(self, seeded_task):
        _, _, _, task_id = seeded_task
        result = flag_blocker(task_id=task_id, description="Waiting on assets", category="external")
        assert "blocker_id" in result
        assert result["category"] == "external"


# ---------------------------------------------------------------------------
# Velocity + Patterns
# ---------------------------------------------------------------------------

class TestVelocityTools:
    def test_record_velocity(self, seeded_cycle):
        user_id, project_id, cycle_id = seeded_cycle
        result = record_velocity(
            project_id=project_id, cycle_id=cycle_id,
            planned_points=15, delivered_points=10, cycle_name="Week 1",
        )
        assert result["planned_points"] == 15
        assert result["delivered_points"] == 10

    def test_get_pace_history_empty(self, ddb):
        result = get_pace_history(project_id="nonexistent", num_cycles=3)
        assert result["cycle_records"] == []
        assert result["trend"] == "stable"

    def test_get_pace_history_with_data(self, seeded_cycle):
        _, project_id, cycle_id = seeded_cycle
        record_velocity(
            project_id=project_id, cycle_id=cycle_id,
            planned_points=10, delivered_points=8, cycle_name="W1",
        )
        result = get_pace_history(project_id=project_id, num_cycles=3)
        assert len(result["cycle_records"]) == 1
        assert result["average_pace"] == 8.0


class TestPatternTools:
    def test_get_patterns_empty(self, ddb, user_id):
        result = get_user_patterns(user_id=user_id)
        assert result["found"] is False
        assert result["cycle_count"] == 0

    def test_update_and_get_patterns(self, ddb, user_id):
        update_user_patterns(
            user_id=user_id, delivered_points=10,
            planned_points=15, new_blockers=["time"],
        )
        result = get_user_patterns(user_id=user_id)
        assert result["found"] is True
        assert result["cycle_count"] == 1
        assert result["avg_pace"] == 10.0
        assert "time" in result["common_blockers"]


# ---------------------------------------------------------------------------
# Onboarding + Preferences
# ---------------------------------------------------------------------------

class TestOnboarding:
    def test_complete_onboarding(self, seeded_user):
        result = complete_onboarding(user_id=seeded_user)
        assert result["onboarded"] is True


class TestPreferences:
    def test_set_timezone(self, seeded_user):
        result = set_user_preference(user_id=seeded_user, preference="timezone", value="America/Los_Angeles")
        assert result["updated"] is True

    def test_set_checkin_time(self, seeded_user):
        result = set_user_preference(user_id=seeded_user, preference="checkin_time", value="08:30")
        assert result["updated"] is True

    def test_set_planning_day(self, seeded_user):
        result = set_user_preference(user_id=seeded_user, preference="planning_day", value="7")
        assert result["updated"] is True
        assert result["value"] == "7"


# ---------------------------------------------------------------------------
# Habit CRUD
# ---------------------------------------------------------------------------

class TestHabitTools:
    def test_create_habit(self, seeded_user):
        result = create_habit(user_id=seeded_user, title="Write 30 min", frequency="daily")
        assert "habit_id" in result
        assert result["title"] == "Write 30 min"
        assert result["frequency"] == "daily"

    def test_list_habits_empty(self, seeded_user):
        result = list_habits(user_id=seeded_user)
        assert result["habits"] == []

    def test_list_habits_with_habit(self, seeded_user):
        create_habit(user_id=seeded_user, title="Exercise", frequency="3x_week")
        result = list_habits(user_id=seeded_user)
        assert len(result["habits"]) == 1
        assert result["habits"][0]["title"] == "Exercise"
        assert result["habits"][0]["done_today"] is False

    def test_complete_habit(self, seeded_user):
        h = create_habit(user_id=seeded_user, title="Read", frequency="daily")
        result = complete_habit(user_id=seeded_user, habit_id=h["habit_id"])
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 1

    def test_complete_habit_idempotent(self, seeded_user):
        h = create_habit(user_id=seeded_user, title="Read", frequency="daily")
        complete_habit(user_id=seeded_user, habit_id=h["habit_id"])
        result = complete_habit(user_id=seeded_user, habit_id=h["habit_id"])
        assert result.get("already_done") is True
        assert result["current_streak"] == 1

    def test_complete_habit_not_found(self, seeded_user):
        result = complete_habit(user_id=seeded_user, habit_id="nonexistent")
        assert "not found" in result["error"]

    def test_list_habits_shows_done_today(self, seeded_user):
        h = create_habit(user_id=seeded_user, title="Write", frequency="daily")
        complete_habit(user_id=seeded_user, habit_id=h["habit_id"])
        result = list_habits(user_id=seeded_user)
        assert result["habits"][0]["done_today"] is True

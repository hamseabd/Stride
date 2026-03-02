from shared.models import User, Project, WorkCycle, Task, Checkin, Blocker, Velocity, UserPattern, Habit


class TestUser:
    def test_defaults(self):
        u = User(user_id="u1")
        assert u.user_id == "u1"
        assert u.onboarded is False
        assert u.timezone == "America/New_York"
        assert u.checkin_time == "09:00"
        assert u.evening_time == "18:00"
        assert u.planning_day == 1

    def test_model_dump(self):
        u = User(user_id="u1", phone="+15551234567")
        d = u.model_dump()
        assert d["user_id"] == "u1"
        assert d["phone"] == "+15551234567"
        assert "timezone" in d


class TestProject:
    def test_defaults(self):
        p = Project(user_id="u1")
        assert p.target_date == ""
        assert p.name == ""
        assert p.project_id  # auto-generated UUID

    def test_with_target_date(self):
        p = Project(user_id="u1", name="Portfolio", target_date="2026-06-01")
        assert p.target_date == "2026-06-01"
        assert p.name == "Portfolio"


class TestTask:
    def test_defaults(self):
        t = Task(cycle_id="c1", title="Do stuff")
        assert t.status == "todo"
        assert t.estimate == 0
        assert t.status_changed_at  # auto-generated timestamp

    def test_status_changed_at_exists(self):
        t = Task(cycle_id="c1", title="Test")
        d = t.model_dump()
        assert "status_changed_at" in d


class TestBlocker:
    def test_defaults(self):
        b = Blocker(task_id="t1", description="Waiting on API")
        assert b.category == ""
        assert b.resolved is False

    def test_with_category(self):
        b = Blocker(task_id="t1", description="Too big", category="scope")
        assert b.category == "scope"


class TestVelocity:
    def test_defaults(self):
        v = Velocity(cycle_id="c1", project_id="p1")
        assert v.active_project_count == 0
        assert v.planned_points == 0
        assert v.delivered_points == 0

    def test_with_active_count(self):
        v = Velocity(cycle_id="c1", project_id="p1", active_project_count=3)
        assert v.active_project_count == 3


class TestUserPattern:
    def test_defaults(self):
        up = UserPattern(user_id="u1")
        assert up.preferred_tone == "balanced"
        assert up.avg_pace == 0.0
        assert up.cycle_count == 0

    def test_with_tone(self):
        up = UserPattern(user_id="u1", preferred_tone="direct")
        assert up.preferred_tone == "direct"


class TestHabit:
    def test_defaults(self):
        h = Habit(user_id="u1", title="Write")
        assert h.frequency == "daily"
        assert h.current_streak == 0
        assert h.longest_streak == 0
        assert h.last_completed == ""
        assert h.active is True

    def test_with_frequency(self):
        h = Habit(user_id="u1", title="Exercise", frequency="3x_week")
        assert h.frequency == "3x_week"

    def test_model_dump(self):
        h = Habit(user_id="u1", title="Read")
        d = h.model_dump()
        assert d["user_id"] == "u1"
        assert d["title"] == "Read"
        assert "habit_id" in d
        assert "created_at" in d


class TestWorkCycle:
    def test_defaults(self):
        wc = WorkCycle(project_id="p1")
        assert wc.status == "active"
        assert wc.cycle_id


class TestCheckin:
    def test_defaults(self):
        c = Checkin(user_id="u1", did="stuff", doing="more")
        assert c.blocked == ""
        assert c.date  # auto-generated

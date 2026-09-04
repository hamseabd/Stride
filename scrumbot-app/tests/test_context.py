"""Tests for P0: user context pre-loading."""

from datetime import datetime, timezone as _tz
from unittest.mock import patch

from functions.sms.handler import (
    _build_user_context, _STATIC_PREFIX,
    _ONBOARDING_ADDENDUM, _TOO_LONG_REPLY, _BLOCKED_REPLY, _WELCOME_BACK,
)


class TestBuildUserContext:
    def _user(self, **overrides):
        base = {
            "timezone": "America/Chicago",
            "preferred_tone": "direct",
            "name": "Hamse",
            "planning_day": 1,
        }
        base.update(overrides)
        return base

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.get_pace_history")
    @patch("functions.sms.handler.get_cycle_data")
    @patch("functions.sms.handler.list_active_projects")
    def test_full_context(self, mock_projects, mock_cycle, mock_pace, mock_habits, mock_patterns):
        mock_projects.return_value = {
            "projects": [{
                "project_id": "p1", "name": "Portfolio", "target_date": "2026-06-01",
                "description": "Phase 1: Research. Phase 2: Build. Phase 3: Launch.",
                "active_cycle": {"cycle_id": "c1", "name": "Week 1"},
            }]
        }
        mock_cycle.return_value = {
            "tasks": [
                {"title": "Wireframes", "status": "in_progress", "estimate_label": "M"},
                {"title": "Logo", "status": "done", "estimate_label": "S"},
            ],
            "cycle": {},
        }
        mock_pace.return_value = {
            "cycle_records": [
                {"delivered_points": 10, "planned_points": 15},
            ],
        }
        mock_habits.return_value = {
            "habits": [{"title": "Write daily", "frequency": "daily", "current_streak": 5, "done_today": False}]
        }
        mock_patterns.return_value = {
            "found": True, "avg_completion_rate": 0.72, "avg_pace": 12,
            "common_blockers": ["external deps"], "cycle_count": 4,
        }

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False)

        assert "Hamse" in ctx
        assert "America/Chicago" in ctx
        assert "direct" in ctx
        # Active goals section
        assert "Active goals:" in ctx
        assert "Portfolio" in ctx
        assert "due 2026-06-01" in ctx
        # Phase plan from description
        assert "Plan:" in ctx
        assert "Phase 1: Research" in ctx
        # Days remaining
        assert "days" in ctx.lower()
        # Tasks
        assert "Wireframes" in ctx
        assert "a day or two" in ctx  # M estimate translated
        assert "Logo" in ctx
        # Velocity history
        assert "History:" in ctx
        assert "10/15" in ctx
        # Habits
        assert "Write daily" in ctx
        assert "streak: 5" in ctx
        # Patterns
        assert "72%" in ctx
        assert "external deps" in ctx
        assert "Do NOT call list_active_projects" in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_new_user_no_projects(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=True)

        assert "ONBOARDING" in ctx.upper() or "NEW USER" in ctx.upper()
        assert "what you want to finish" in ctx.lower() or "new user" in ctx.lower()

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_new_user_includes_inferred_timezone(self, mock_projects, mock_habits, mock_patterns):
        """New users should see inferred timezone from their area code."""
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        # +1404 = Atlanta = Eastern
        ctx = _build_user_context("+14045551234", self._user(), is_new_user=True)
        assert "Inferred timezone" in ctx
        assert "America/New_York" in ctx
        assert "Eastern time" in ctx

        # +1312 = Chicago = Central
        ctx = _build_user_context("+13125551234", self._user(), is_new_user=True)
        assert "America/Chicago" in ctx
        assert "Central time" in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_existing_user_no_inferred_timezone(self, mock_projects, mock_habits, mock_patterns):
        """Existing users should NOT see inferred timezone."""
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        ctx = _build_user_context("+14045551234", self._user(), is_new_user=False)
        assert "Inferred timezone" not in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_low_completion_rate_warning(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {
            "found": True, "avg_completion_rate": 0.45,
            "common_blockers": [], "cycle_count": 5,
        }

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False)

        assert "low" in ctx.lower() or "realistically" in ctx.lower()

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_error_handling_graceful(self, mock_projects, mock_habits, mock_patterns):
        """If DynamoDB fails, context should still build without crashing."""
        mock_projects.return_value = {"error": "db timeout"}
        mock_habits.return_value = {"error": "db timeout"}
        mock_patterns.return_value = {"error": "db timeout"}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False)

        assert "user_id" in ctx.lower() or "+15551234567" in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.get_pace_history")
    @patch("functions.sms.handler.get_cycle_data")
    @patch("functions.sms.handler.list_active_projects")
    def test_backlog_goals(self, mock_projects, mock_cycle, mock_pace, mock_habits, mock_patterns):
        mock_projects.return_value = {
            "projects": [
                {"project_id": "p1", "name": "Portfolio", "target_date": "2026-06-01",
                 "description": "Phase 1: Research. Phase 2: Build.",
                 "active_cycle": {"cycle_id": "c1", "name": "Week 1"}},
                {"project_id": "p2", "name": "YouTube Channel", "target_date": "",
                 "description": "", "active_cycle": None},
            ]
        }
        mock_cycle.return_value = {"tasks": [{"title": "Wireframes", "status": "todo", "estimate_label": "M"}], "cycle": {}}
        mock_pace.return_value = {"cycle_records": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False)

        assert "Active goals:" in ctx
        assert "Portfolio" in ctx
        assert "Backlog" in ctx
        assert "YouTube Channel" in ctx


class TestSessionAwareContext:
    def _user(self):
        return {"timezone": "America/New_York", "preferred_tone": "balanced", "name": "Test"}

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_recent_outbound_injects_session(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        now = datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
        outbound = {"message_type": "morning_reminder", "sent_at": now}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False,
                                  latest_outbound=outbound)
        assert "replying to a morning check-in message" in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_stale_outbound_not_injected(self, mock_projects, mock_habits, mock_patterns):
        """Outbound older than 6 hours should NOT inject session context."""
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        from datetime import timedelta
        old = (datetime.now(_tz.utc) - timedelta(hours=8)).isoformat().replace("+00:00", "Z")
        outbound = {"message_type": "morning_reminder", "sent_at": old}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False,
                                  latest_outbound=outbound)
        assert "replying to" not in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_no_outbound_no_session(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False,
                                  latest_outbound=None)
        assert "replying to" not in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_friday_review_session(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        now = datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
        outbound = {"message_type": "friday_review", "sent_at": now}

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False,
                                  latest_outbound=outbound)
        assert "replying to a Friday review message" in ctx

    @patch("functions.sms.handler.get_user_patterns")
    @patch("functions.sms.handler.list_habits")
    @patch("functions.sms.handler.list_active_projects")
    def test_outbound_without_message_type_ignored(self, mock_projects, mock_habits, mock_patterns):
        mock_projects.return_value = {"projects": []}
        mock_habits.return_value = {"habits": []}
        mock_patterns.return_value = {"found": False}

        now = datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
        outbound = {"sent_at": now}  # no message_type

        ctx = _build_user_context("+15551234567", self._user(), is_new_user=False,
                                  latest_outbound=outbound)
        assert "replying to" not in ctx


class TestTooLongReply:
    """Too-long messages get a specific helpful reply, not a generic block."""

    def test_too_long_reply_mentions_one_goal(self):
        assert "one goal" in _TOO_LONG_REPLY.lower()

    def test_too_long_differs_from_blocked(self):
        assert _TOO_LONG_REPLY != _BLOCKED_REPLY

    def test_too_long_under_sms_limit(self):
        assert len(_TOO_LONG_REPLY) <= 480


class TestOnboardingAddendum:
    """Onboarding prompt is adaptive, not rigid."""

    def test_adaptive_not_sequential(self):
        """Should mention adaptive flow, not rigid numbered steps."""
        assert "ADAPTIVE" in _ONBOARDING_ADDENDUM.upper()
        assert "ROLL WITH IT" in _ONBOARDING_ADDENDUM.upper()

    def test_handles_multiple_goals(self):
        assert "MULTIPLE" in _ONBOARDING_ADDENDUM.upper()

    def test_handles_vague_goals(self):
        assert "VAGUE" in _ONBOARDING_ADDENDUM.upper()

    def test_handles_habits(self):
        assert "create_habit" in _ONBOARDING_ADDENDUM

    def test_prioritizes_user_input(self):
        """Should tell agent to respond to what user said first."""
        assert "PRIORITY" in _ONBOARDING_ADDENDUM.upper()
        assert "momentum" in _ONBOARDING_ADDENDUM.lower()

    def test_welcome_message_explains_stride(self):
        """First message should explain what Stride does."""
        assert "break it down" in _ONBOARDING_ADDENDUM
        # "plan each\nweek" wraps across lines in the welcome message
        assert "plan each" in _ONBOARDING_ADDENDUM
        assert "check in daily" in _ONBOARDING_ADDENDUM

    def test_no_scrum_jargon_in_user_facing_text(self):
        """User-facing messages should not contain Scrum jargon.
        The RULES section mentions 'sprints' to tell the agent not to use it —
        that's internal instruction, not user-facing."""
        # Check the welcome message specifically (the part users see)
        welcome_start = _ONBOARDING_ADDENDUM.index('"Hey!')
        welcome_end = _ONBOARDING_ADDENDUM.index('What should I call you?"') + len('What should I call you?"')
        welcome = _ONBOARDING_ADDENDUM[welcome_start:welcome_end].lower()
        for term in ["sprint", "story point", "standup", "fibonacci", "velocity"]:
            assert term not in welcome, f"Jargon '{term}' found in welcome message"


class TestWelcomeBack:
    """Re-subscribe message explains what Stride does."""

    def test_explains_stride(self):
        assert "break it down" in _WELCOME_BACK or "break them down" in _WELCOME_BACK

    def test_under_sms_limit(self):
        assert len(_WELCOME_BACK) <= 480


class TestStaticPrefix:
    def test_above_caching_threshold(self):
        """Static prefix must be >1024 tokens for Anthropic caching to work."""
        # Rough estimate: 4 chars per token
        estimated_tokens = len(_STATIC_PREFIX) // 4
        assert estimated_tokens > 1024, f"Static prefix too short for caching: ~{estimated_tokens} tokens"

    def test_contains_core_rules(self):
        assert "Stride" in _STATIC_PREFIX
        assert "NEVER" in _STATIC_PREFIX  # estimate hiding rule
        assert "SMS" in _STATIC_PREFIX


def test_context_includes_project_and_task_ids(ddb, seeded_task):
    """Tools take project_id / task_id; the model can only supply them if the context shows them."""
    from functions.sms.handler import _build_user_context
    user_id, project_id, cycle_id, task_id = seeded_task
    ctx = _build_user_context(user_id, {"planning_day": 1, "timezone": "America/New_York"}, is_new_user=False)
    assert f"(id {project_id})" in ctx
    assert f"(id {task_id})" in ctx


def test_context_tells_model_to_use_listed_ids(ddb, seeded_task):
    from functions.sms.handler import _build_user_context
    user_id, *_ = seeded_task
    ctx = _build_user_context(user_id, {"planning_day": 1, "timezone": "America/New_York"}, is_new_user=False)
    assert "never guess an id" in ctx

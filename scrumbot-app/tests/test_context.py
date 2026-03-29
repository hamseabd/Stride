"""Tests for P0: user context pre-loading."""

from unittest.mock import patch

from functions.sms.handler import _build_user_context, _STATIC_PREFIX


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
        assert "What should I call you" in ctx

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

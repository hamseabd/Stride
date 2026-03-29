"""Tests for scheduler logic — message type selection, time windows, dedup, tone derivation."""

from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

from functions.scheduler.handler import (
    _in_window,
    _determine_message_type,
    _build_morning_reminder,
    _build_evening_checkin,
    _build_midweek_adjust,
    _build_planning_prompt,
    _build_review_prompt,
    _derive_tone,
    ESTIMATE_LABELS,
)


# ── Time window tests ─────────────────────────────────────────────────────────


class TestInWindow:
    def test_exact_match(self):
        now = datetime(2026, 3, 23, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00") is True

    def test_within_window(self):
        now = datetime(2026, 3, 23, 9, 10, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00") is True

    def test_at_window_edge(self):
        now = datetime(2026, 3, 23, 9, 14, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00") is True

    def test_past_window(self):
        now = datetime(2026, 3, 23, 9, 15, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00") is False

    def test_before_window(self):
        now = datetime(2026, 3, 23, 8, 59, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00") is False

    def test_invalid_time_defaults_9am(self):
        now = datetime(2026, 3, 23, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "invalid") is True

    def test_custom_window(self):
        now = datetime(2026, 3, 23, 9, 25, tzinfo=ZoneInfo("America/New_York"))
        assert _in_window(now, "09:00", window_minutes=30) is True


# ── Message type determination ────────────────────────────────────────────────


class TestDetermineMessageType:
    def _user(self, checkin="09:00", evening="18:00"):
        return {"checkin_time": checkin, "evening_time": evening}

    def test_monday_morning_planning(self):
        # Monday 9:05 AM
        now = datetime(2026, 3, 23, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "monday_planning"

    def test_tuesday_morning_reminder(self):
        # Tuesday 9:05 AM
        now = datetime(2026, 3, 24, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "morning_reminder"

    def test_wednesday_morning_reminder(self):
        # Wednesday 9:05 AM
        now = datetime(2026, 3, 25, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "morning_reminder"

    def test_wednesday_evening_midweek(self):
        # Wednesday 6:05 PM
        now = datetime(2026, 3, 25, 18, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "midweek_adjust"

    def test_thursday_evening_checkin(self):
        # Thursday 6:05 PM
        now = datetime(2026, 3, 26, 18, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "evening_checkin"

    def test_friday_evening_review(self):
        # Friday 6:05 PM
        now = datetime(2026, 3, 27, 18, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "friday_review"

    def test_saturday_none(self):
        # Saturday 9:05 AM — no messages on weekends
        now = datetime(2026, 3, 28, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) is None

    def test_sunday_none(self):
        # Sunday 9:05 AM
        now = datetime(2026, 3, 29, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) is None

    def test_monday_outside_window(self):
        # Monday 10:00 AM — past the 15-min window
        now = datetime(2026, 3, 23, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) is None

    def test_custom_checkin_time(self):
        # Tuesday 8:05 AM with checkin at 08:00
        now = datetime(2026, 3, 24, 8, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user(checkin="08:00")) == "morning_reminder"

    def test_tuesday_evening_checkin(self):
        # Tuesday 6:05 PM
        now = datetime(2026, 3, 24, 18, 5, tzinfo=ZoneInfo("America/New_York"))
        assert _determine_message_type(now, self._user()) == "evening_checkin"


# ── Message builders ──────────────────────────────────────────────────────────


class TestMessageBuilders:
    def test_evening_checkin_static(self):
        msg = _build_evening_checkin()
        assert "how" in msg.lower()
        assert "?" in msg

    @patch("functions.scheduler.handler.list_active_projects")
    def test_morning_reminder_no_projects(self, mock_projects):
        mock_projects.return_value = {"projects": []}
        msg = _build_morning_reminder("+15551234567")
        assert "morning" in msg.lower()

    @patch("functions.scheduler.handler.get_cycle_data")
    @patch("functions.scheduler.handler.list_active_projects")
    def test_morning_reminder_with_tasks(self, mock_projects, mock_cycle):
        mock_projects.return_value = {
            "projects": [{
                "project_id": "p1",
                "name": "Portfolio",
                "target_date": "",
                "active_cycle": {"cycle_id": "c1", "name": "Week 1"},
            }]
        }
        mock_cycle.return_value = {
            "tasks": [
                {"title": "Wireframes", "status": "todo", "estimate_label": "M"},
                {"title": "Logo", "status": "done", "estimate_label": "S"},
            ],
            "cycle": {},
        }
        msg = _build_morning_reminder("+15551234567")
        assert "Wireframes" in msg
        assert "a day or two" in msg
        assert "Portfolio" in msg
        # Done tasks should be excluded
        assert "Logo" not in msg

    @patch("functions.scheduler.handler.get_cycle_data")
    @patch("functions.scheduler.handler.list_active_projects")
    def test_planning_prompt_with_projects(self, mock_projects, mock_cycle):
        mock_projects.return_value = {
            "projects": [
                {"project_id": "p1", "name": "Portfolio", "target_date": "2026-06-01",
                 "active_cycle": {"cycle_id": "c1"}},
                {"project_id": "p2", "name": "Blog", "target_date": "",
                 "active_cycle": None},
            ]
        }
        mock_cycle.return_value = {
            "tasks": [
                {"title": "A", "status": "done"},
            ],
            "cycle": {},
        }
        msg = _build_planning_prompt("+15551234567")
        assert "New week" in msg
        assert "Portfolio" in msg
        # Blog is a backlog goal — should be surfaced
        assert "Blog" in msg

    @patch("functions.scheduler.handler.get_cycle_data")
    @patch("functions.scheduler.handler.list_active_projects")
    def test_review_prompt_with_progress(self, mock_projects, mock_cycle):
        mock_projects.return_value = {
            "projects": [{
                "project_id": "p1",
                "name": "Portfolio",
                "target_date": "",
                "active_cycle": {"cycle_id": "c1"},
            }]
        }
        mock_cycle.return_value = {
            "tasks": [
                {"title": "A", "status": "done"},
                {"title": "B", "status": "done"},
                {"title": "C", "status": "todo"},
            ],
            "cycle": {},
        }
        msg = _build_review_prompt("+15551234567")
        assert "2 of 3" in msg

    @patch("functions.scheduler.handler.get_cycle_data")
    @patch("functions.scheduler.handler.list_active_projects")
    def test_midweek_adjust_with_progress(self, mock_projects, mock_cycle):
        mock_projects.return_value = {
            "projects": [{
                "project_id": "p1",
                "name": "Portfolio",
                "target_date": "",
                "active_cycle": {"cycle_id": "c1"},
            }]
        }
        mock_cycle.return_value = {
            "tasks": [
                {"title": "A", "status": "done"},
                {"title": "B", "status": "todo"},
            ],
            "cycle": {},
        }
        msg = _build_midweek_adjust("+15551234567")
        assert "1 of 2" in msg


# ── Estimate labels ───────────────────────────────────────────────────────────


class TestEstimateLabels:
    def test_all_labels_present(self):
        assert set(ESTIMATE_LABELS.keys()) == {"S", "M", "L", "XL"}

    def test_s_label(self):
        assert ESTIMATE_LABELS["S"] == "a few hours"

    def test_xl_label(self):
        assert ESTIMATE_LABELS["XL"] == "more than a week"


# ── Tone derivation ──────────────────────────────────────────────────────────


class TestToneDerivation:
    @patch("functions.scheduler.handler.update_preferred_tone")
    @patch("functions.scheduler.handler.get_outbound_since")
    def test_fast_replies_direct(self, mock_outbound, mock_update):
        """Fast replies + high reply rate → direct."""
        mock_outbound.return_value = [
            {"sent_at": "2026-03-20T09:00:00", "replied_at": "2026-03-20T09:10:00", "message_type": "morning_reminder"},
            {"sent_at": "2026-03-21T09:00:00", "replied_at": "2026-03-21T09:15:00", "message_type": "morning_reminder"},
            {"sent_at": "2026-03-22T09:00:00", "replied_at": "2026-03-22T09:05:00", "message_type": "morning_reminder"},
        ]
        now = datetime(2026, 4, 3, 18, 5, tzinfo=ZoneInfo("America/New_York"))  # Week 14 (even)
        _derive_tone("+15551234567", now)
        mock_update.assert_called_once_with("+15551234567", "direct")

    @patch("functions.scheduler.handler.update_preferred_tone")
    @patch("functions.scheduler.handler.get_outbound_since")
    def test_slow_replies_encouraging(self, mock_outbound, mock_update):
        """Slow replies → encouraging."""
        mock_outbound.return_value = [
            {"sent_at": "2026-03-20T09:00:00", "replied_at": "2026-03-20T12:00:00", "message_type": "morning_reminder"},
            {"sent_at": "2026-03-21T09:00:00", "message_type": "morning_reminder"},  # no reply
            {"sent_at": "2026-03-22T09:00:00", "message_type": "morning_reminder"},  # no reply
        ]
        now = datetime(2026, 4, 3, 18, 5, tzinfo=ZoneInfo("America/New_York"))  # Week 14 (even)
        _derive_tone("+15551234567", now)
        mock_update.assert_called_once_with("+15551234567", "encouraging")

    @patch("functions.scheduler.handler.update_preferred_tone")
    @patch("functions.scheduler.handler.get_outbound_since")
    def test_odd_week_skips(self, mock_outbound, mock_update):
        """Odd weeks should skip tone derivation."""
        now = datetime(2026, 4, 10, 18, 5, tzinfo=ZoneInfo("America/New_York"))  # Week 15 (odd)
        _derive_tone("+15551234567", now)
        mock_outbound.assert_not_called()
        mock_update.assert_not_called()

    @patch("functions.scheduler.handler.update_preferred_tone")
    @patch("functions.scheduler.handler.get_outbound_since")
    def test_no_records_skips(self, mock_outbound, mock_update):
        """No outbound records → skip."""
        mock_outbound.return_value = []
        now = datetime(2026, 4, 3, 18, 5, tzinfo=ZoneInfo("America/New_York"))  # Week 14 (even)
        _derive_tone("+15551234567", now)
        mock_update.assert_not_called()

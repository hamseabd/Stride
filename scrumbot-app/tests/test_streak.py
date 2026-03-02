from shared.tools import _is_streak_alive


class TestDaily:
    def test_consecutive_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-02", "daily") is True

    def test_skipped_day(self):
        assert _is_streak_alive("2026-03-01", "2026-03-03", "daily") is False

    def test_same_day(self):
        assert _is_streak_alive("2026-03-01", "2026-03-01", "daily") is False

    def test_no_last_completed(self):
        assert _is_streak_alive("", "2026-03-01", "daily") is False


class TestWeekdays:
    def test_mon_to_tue(self):
        # 2026-03-02 = Monday, 2026-03-03 = Tuesday
        assert _is_streak_alive("2026-03-02", "2026-03-03", "weekdays") is True

    def test_fri_to_mon(self):
        # 2026-03-06 = Friday, 2026-03-09 = Monday
        assert _is_streak_alive("2026-03-06", "2026-03-09", "weekdays") is True

    def test_thu_to_sat_breaks(self):
        # 2026-03-05 = Thursday, 2026-03-07 = Saturday — gap=2, not Fri→Mon
        assert _is_streak_alive("2026-03-05", "2026-03-07", "weekdays") is False

    def test_wed_to_fri_breaks(self):
        # 2026-03-04 = Wednesday, 2026-03-06 = Friday — gap=2, skipped Thu
        assert _is_streak_alive("2026-03-04", "2026-03-06", "weekdays") is False

    def test_consecutive_weekdays(self):
        # 2026-03-03 = Tuesday, 2026-03-04 = Wednesday
        assert _is_streak_alive("2026-03-03", "2026-03-04", "weekdays") is True


class TestWeekly:
    def test_within_7_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-07", "weekly") is True

    def test_exactly_7_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-08", "weekly") is True

    def test_beyond_7_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-09", "weekly") is False

    def test_next_day(self):
        assert _is_streak_alive("2026-03-01", "2026-03-02", "weekly") is True


class TestThreePerWeek:
    def test_within_7_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-07", "3x_week") is True

    def test_beyond_7_days(self):
        assert _is_streak_alive("2026-03-01", "2026-03-09", "3x_week") is False

    def test_next_day(self):
        assert _is_streak_alive("2026-03-01", "2026-03-02", "3x_week") is True


class TestEdgeCases:
    def test_unknown_frequency_falls_back_to_daily(self):
        assert _is_streak_alive("2026-03-01", "2026-03-02", "unknown") is True
        assert _is_streak_alive("2026-03-01", "2026-03-03", "unknown") is False

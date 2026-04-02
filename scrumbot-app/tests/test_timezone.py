"""Tests for shared/timezone.py — area code to IANA timezone inference."""

from shared.timezone import infer_timezone_from_phone, TZ_DISPLAY_NAMES


class TestInferTimezone:
    def test_eastern_atlanta(self):
        assert infer_timezone_from_phone("+14045551234") == "America/New_York"

    def test_eastern_nyc(self):
        assert infer_timezone_from_phone("+12125551234") == "America/New_York"

    def test_central_chicago(self):
        assert infer_timezone_from_phone("+13125551234") == "America/Chicago"

    def test_central_houston(self):
        assert infer_timezone_from_phone("+17135551234") == "America/Chicago"

    def test_mountain_denver(self):
        assert infer_timezone_from_phone("+13035551234") == "America/Denver"

    def test_mountain_salt_lake(self):
        assert infer_timezone_from_phone("+18015551234") == "America/Denver"

    def test_pacific_la(self):
        assert infer_timezone_from_phone("+12135551234") == "America/Los_Angeles"

    def test_pacific_sf(self):
        assert infer_timezone_from_phone("+14155551234") == "America/Los_Angeles"

    def test_pacific_seattle(self):
        assert infer_timezone_from_phone("+12065551234") == "America/Los_Angeles"

    def test_pacific_vegas(self):
        assert infer_timezone_from_phone("+17025551234") == "America/Los_Angeles"

    def test_arizona_phoenix(self):
        assert infer_timezone_from_phone("+16025551234") == "America/Phoenix"

    def test_arizona_tucson(self):
        assert infer_timezone_from_phone("+15205551234") == "America/Phoenix"

    def test_alaska(self):
        assert infer_timezone_from_phone("+19075551234") == "America/Anchorage"

    def test_hawaii(self):
        assert infer_timezone_from_phone("+18085551234") == "Pacific/Honolulu"

    def test_unknown_area_code_defaults_eastern(self):
        assert infer_timezone_from_phone("+19995551234") == "America/New_York"

    def test_short_number_defaults_eastern(self):
        assert infer_timezone_from_phone("+1") == "America/New_York"

    def test_international_defaults_eastern(self):
        assert infer_timezone_from_phone("+442071234567") == "America/New_York"

    def test_no_plus_prefix(self):
        assert infer_timezone_from_phone("14045551234") == "America/New_York"

    def test_empty_string_defaults_eastern(self):
        assert infer_timezone_from_phone("") == "America/New_York"


class TestDisplayNames:
    def test_all_timezones_have_display_names(self):
        """Every timezone in the lookup should have a display name."""
        from shared.timezone import _AREA_CODE_TZ
        tz_values = set(_AREA_CODE_TZ.values())
        for tz in tz_values:
            assert tz in TZ_DISPLAY_NAMES, f"Missing display name for {tz}"

    def test_display_name_format(self):
        """Display names should end with 'time'."""
        for tz, display in TZ_DISPLAY_NAMES.items():
            assert display.endswith("time"), f"{tz} display name doesn't end with 'time': {display}"

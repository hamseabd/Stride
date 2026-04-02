from shared.guards import check_message, MAX_MESSAGE_LENGTH


class TestCheckMessage:
    def test_none(self):
        assert check_message(None) == "empty"

    def test_empty_string(self):
        assert check_message("") == "empty"

    def test_whitespace_only(self):
        assert check_message("   ") == "empty"

    def test_too_long(self):
        assert check_message("a" * (MAX_MESSAGE_LENGTH + 1)) == "too_long"

    def test_exactly_at_limit(self):
        assert check_message("a" * MAX_MESSAGE_LENGTH) is None

    def test_valid_message(self):
        assert check_message("hello") is None

    def test_valid_with_spaces(self):
        assert check_message("  hello world  ") is None

    def test_limit_is_1600(self):
        """Inbound SMS limit matches Twilio's concatenated SMS max."""
        assert MAX_MESSAGE_LENGTH == 1600

    def test_long_multi_goal_message_passes(self):
        """Real user message with multiple goals (like Malik's) should pass."""
        malik_msg = (
            "I want to set restrictive rules on my day to day schedule and "
            "create goals in couple of different places in my life. "
            "I want to achieve these goals by the remaining or end of the year. "
            "I have a trucking automation software that I want to sale. "
            "Now I want to have 10 clients that are paying by the end of the year. "
            "I want to get a new software engineering 1 role at my company. "
            "Also really important. My personal goal: get out of debt. "
            "Currently in 11k debt. Gym 5 days a week. Gain 20 lbs. pray 5x a day."
        )
        assert len(malik_msg) < MAX_MESSAGE_LENGTH
        assert check_message(malik_msg) is None

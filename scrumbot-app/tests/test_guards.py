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
        """A long first message listing several goals at once should pass (synthetic text)."""
        multi_goal_msg = (
            "Hi, I'm Jordan. I have a few things I want to get done before the end of the year "
            "and I keep starting them and dropping them. "
            "First, I'm building a Chrome extension that blocks distracting sites "
            "and I want it live on the Web Store by October. "
            "After launch I'd like 50 people actually using it every week. "
            "Second, I want to finish the online course on databases I bought last spring. "
            "Third, I want to write one blog post a month about what I'm building. "
            "Also, read 12 books this year and run a 10k in the fall."
        )
        assert len(multi_goal_msg) < MAX_MESSAGE_LENGTH
        assert check_message(multi_goal_msg) is None

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

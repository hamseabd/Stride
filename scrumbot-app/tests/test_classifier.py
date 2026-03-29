"""Tests for Haiku intent classifier."""

from unittest.mock import patch, MagicMock

from shared.classifier import classify_intent, VALID_INTENTS


def _mock_haiku_response(intent_text: str):
    """Create a mock Anthropic response with the given text."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=intent_text)]
    return mock_resp


class TestClassifyIntent:
    @patch("shared.classifier._get_client")
    def test_feedback(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("feedback")
        mock_get_client.return_value = mock_client
        assert classify_intent("This isn't helpful at all") == "feedback"

    @patch("shared.classifier._get_client")
    def test_remind_me(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("remind_me")
        mock_get_client.return_value = mock_client
        assert classify_intent("Yeah sure remind me") == "remind_me"

    @patch("shared.classifier._get_client")
    def test_no_reminders(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("no_reminders")
        mock_get_client.return_value = mock_client
        assert classify_intent("Stop sending me reminders please") == "no_reminders"

    @patch("shared.classifier._get_client")
    def test_help(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("help")
        mock_get_client.return_value = mock_client
        assert classify_intent("How does this work?") == "help"

    @patch("shared.classifier._get_client")
    def test_conversation(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("conversation")
        mock_get_client.return_value = mock_client
        assert classify_intent("I finished the wireframes today") == "conversation"

    @patch("shared.classifier._get_client")
    def test_conversation_with_remind(self, mock_get_client):
        """'remind me what my tasks are' should be conversation, not remind_me."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("conversation")
        mock_get_client.return_value = mock_client
        assert classify_intent("Can you remind me what my tasks are?") == "conversation"

    @patch("shared.classifier._get_client")
    def test_unknown_intent_falls_back(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("unknown_thing")
        mock_get_client.return_value = mock_client
        assert classify_intent("something weird") == "conversation"

    @patch("shared.classifier._get_client")
    def test_whitespace_stripped(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_haiku_response("  feedback  \n")
        mock_get_client.return_value = mock_client
        assert classify_intent("you should improve this") == "feedback"

    @patch("shared.classifier._get_client")
    def test_api_failure_falls_back(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API timeout")
        mock_get_client.return_value = mock_client
        assert classify_intent("some message") == "conversation"


class TestValidIntents:
    def test_all_intents_present(self):
        assert VALID_INTENTS == {"feedback", "remind_me", "no_reminders", "help", "conversation"}

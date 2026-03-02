import json

from shared.db import get_conversation, save_conversation, get_table


class TestSaveAndLoad:
    def test_empty_history(self, ddb, user_id):
        assert get_conversation(user_id) == []

    def test_roundtrip(self, ddb, user_id):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
        ]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[1]["role"] == "assistant"


class TestStripping:
    def test_strips_tool_use(self, ddb, user_id):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "create a project"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "I'll create that for you"},
                {"type": "toolUse", "toolUseId": "123", "name": "create_project", "input": {}},
            ]},
            {"role": "user", "content": [{"type": "toolResult", "toolUseId": "123", "content": []}]},
        ]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        # toolResult messages are stripped entirely
        # toolUse blocks are stripped from assistant messages
        assert len(loaded) == 2
        assistant_msg = loaded[1]
        for block in assistant_msg["content"]:
            assert block.get("type") != "toolUse"

    def test_strips_tool_result_messages(self, ddb, user_id):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "user", "content": [{"type": "toolResult", "toolUseId": "x", "content": []}]},
        ]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        # Only the first user message should survive — toolResult is stripped
        assert len(loaded) == 1


class TestCap:
    def test_caps_at_20_turns(self, ddb, user_id):
        messages = [{"role": "user", "content": [{"type": "text", "text": f"msg {i}"}]} for i in range(30)]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        assert len(loaded) == 20
        # Should keep the LAST 20
        assert loaded[0]["content"][0]["text"] == "msg 10"


class TestByteSizeSafety:
    def test_trims_if_over_350kb(self, ddb, user_id):
        big_text = "x" * 20_000
        messages = [{"role": "user", "content": [{"type": "text", "text": big_text}]} for _ in range(25)]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        raw = json.dumps(loaded).encode("utf-8")
        assert len(raw) <= 350_000


class TestWeeklyReset:
    def test_resets_on_planning_day(self, ddb, user_id):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]

        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        current_weekday = now.isoweekday()

        # Save the conversation, then manually set last_reset_date to an old date
        # so get_conversation sees "planning day but haven't reset yet"
        save_conversation(user_id, messages, planning_day=current_weekday, user_timezone="America/New_York")

        # Overwrite last_reset_date to simulate a stale record from last week
        table = get_table()
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"},
            UpdateExpression="SET last_reset_date = :old",
            ExpressionAttributeValues={":old": "2026-01-01"},
        )

        loaded = get_conversation(user_id)
        assert loaded == []

    def test_no_reset_on_different_day(self, ddb, user_id):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]

        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        current_weekday = now.isoweekday()
        # Pick a different day
        other_day = (current_weekday % 7) + 1

        save_conversation(user_id, messages, planning_day=other_day, user_timezone="America/New_York")
        loaded = get_conversation(user_id)
        assert len(loaded) == 1

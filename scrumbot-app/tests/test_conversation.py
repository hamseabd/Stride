import json

from shared.db import get_conversation, save_conversation


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
        # Alternating user/assistant messages (realistic conversation)
        messages = []
        for i in range(30):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": [{"type": "text", "text": f"msg {i}"}]})
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



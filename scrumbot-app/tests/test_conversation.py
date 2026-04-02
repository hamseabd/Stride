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


class TestAlternation:
    def test_merges_consecutive_same_role_after_tool_strip(self, ddb, user_id):
        """When tool_result messages are stripped, consecutive assistant messages
        should be merged so the 20-turn count is accurate."""
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "create project"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "creating..."},
                {"type": "toolUse", "toolUseId": "t1", "name": "create_project", "input": {}},
            ]},
            {"role": "user", "content": [{"type": "toolResult", "toolUseId": "t1", "content": []}]},
            {"role": "assistant", "content": [{"type": "text", "text": "done!"}]},
        ]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        # Two assistant messages should merge after tool_result is dropped
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[1]["role"] == "assistant"

    def test_first_message_must_be_user(self, ddb, user_id):
        """If truncation leaves an assistant message first, it should be dropped."""
        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "leftover"}]},
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        ]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        assert loaded[0]["role"] == "user"
        assert len(loaded) == 2

    def test_truncation_drops_leading_assistant(self, ddb, user_id):
        """After 20-turn cap, if first message is assistant, drop it."""
        # Build 22 messages: assistant, user, assistant, user, ...
        messages = []
        for i in range(22):
            role = "assistant" if i % 2 == 0 else "user"
            messages.append({"role": role, "content": [{"type": "text", "text": f"msg {i}"}]})
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        # After truncation [-20:], first message would be assistant (msg 2)
        # Fix should drop it, leaving 19 messages starting with user
        assert loaded[0]["role"] == "user"
        assert all(
            loaded[i]["role"] != loaded[i + 1]["role"]
            for i in range(len(loaded) - 1)
        )


class TestByteSizeSafety:
    def test_trims_if_over_350kb(self, ddb, user_id):
        big_text = "x" * 20_000
        messages = [{"role": "user", "content": [{"type": "text", "text": big_text}]} for _ in range(25)]
        save_conversation(user_id, messages)
        loaded = get_conversation(user_id)
        raw = json.dumps(loaded).encode("utf-8")
        assert len(raw) <= 350_000



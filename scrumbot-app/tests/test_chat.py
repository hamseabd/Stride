"""chat.py is a dev tool, but its turn logic mirrors production and is worth pinning."""

import json

import pytest


@pytest.fixture
def chat_module(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    import importlib
    import chat
    return importlib.reload(chat)


class _Result:
    class metrics:
        accumulated_usage = {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150}

        @staticmethod
        def get_summary():
            return {"total_cycles": 2}

    def __str__(self):
        return "Nice. What's the first step?"


class _FakeModel:
    cache_read_tokens = 400
    cache_write_tokens = 0

    def __init__(self, **kwargs):
        pass

    def update_config(self, **kwargs):
        pass


class _FakeAgent:
    def __init__(self, **kwargs):
        self.messages = list(kwargs.get("messages") or [])

    def __call__(self, message):
        self.messages.append({"role": "user", "content": [{"text": message}]})
        self.messages.append({"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": "create_project",
                          "input": {"user_id": "+15551234567", "name": "Ext", "description": "", "target_date": ""}}},
        ]})
        self.messages.append({"role": "user", "content": [
            {"toolResult": {"toolUseId": "t1", "content": [{"text": "{}"}], "status": "success"}},
        ]})
        self.messages.append({"role": "assistant", "content": [{"text": str(_Result())}]})
        return _Result()


def test_run_turn_returns_structured_record(chat_module, monkeypatch, ddb):
    monkeypatch.setattr(chat_module, "classify_intent", lambda m: "conversation")
    monkeypatch.setattr(chat_module, "Agent", _FakeAgent)
    monkeypatch.setattr(chat_module, "_CachedAnthropicModel", _FakeModel)
    phone = "+15551234567"
    chat_module.ensure_user(phone)

    rec = chat_module.run_turn(phone, "I'm building a browser extension")

    assert rec["intent"] == "conversation"
    assert rec["reply"] == "Nice. What's the first step?"
    assert rec["chars"] == len(rec["reply"])
    assert rec["segments"] == 1
    assert rec["tools"] == [{"name": "create_project",
                             "input": {"name": "Ext", "description": "", "target_date": ""}}]
    assert rec["input_tokens"] == 120 and rec["output_tokens"] == 30
    assert rec["cache_read"] == 400
    assert rec["cost_usd"] == pytest.approx((120 * 3 + 30 * 15 + 400 * 0.30) / 1e6)
    assert rec["latency_ms"] >= 0


def test_run_turn_short_circuits_non_conversation_intents(chat_module, monkeypatch, ddb):
    monkeypatch.setattr(chat_module, "classify_intent", lambda m: "remind_me")
    calls = []
    monkeypatch.setattr(chat_module, "Agent", lambda **k: calls.append(k))
    phone = "+15551234567"
    chat_module.ensure_user(phone)

    rec = chat_module.run_turn(phone, "yes remind me")

    assert rec["intent"] == "remind_me"
    assert "daily check-ins" in rec["reply"]
    assert rec["tools"] == [] and calls == []


def test_tool_input_strips_user_id(chat_module):
    msgs = [{"role": "assistant", "content": [
        {"toolUse": {"name": "list_habits", "input": {"user_id": "+15551234567"}}}]}]
    assert chat_module.extract_tool_calls(msgs) == [{"name": "list_habits", "input": {}}]


def test_dump_spans_writes_parent_child_json(chat_module, tmp_path):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("root") as root:
        root.set_attribute("k", "v")
        with tracer.start_as_current_span("child"):
            pass

    out = tmp_path / "trace.json"
    chat_module.dump_spans(exporter, str(out))
    spans = json.loads(out.read_text())
    by_name = {s["name"]: s for s in spans}
    assert by_name["child"]["parent_id"] == by_name["root"]["span_id"]
    assert by_name["root"]["parent_id"] is None
    assert by_name["root"]["attributes"]["k"] == "v"
    assert by_name["child"]["end_ns"] >= by_name["child"]["start_ns"]


def test_run_turn_opens_root_span(chat_module, monkeypatch, ddb):
    """Local turns get a root span so botocore spans have a parent, like the Lambda."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(chat_module, "get_tracer", lambda: provider.get_tracer("t"))
    monkeypatch.setattr(chat_module, "classify_intent", lambda m: "remind_me")
    phone = "+15551234567"
    chat_module.ensure_user(phone)

    chat_module.run_turn(phone, "remind me")

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["stride.chat.turn"]
    assert spans[0].attributes["user.id"] == phone
    assert spans[0].attributes["intent"] == "remind_me"
    assert spans[0].attributes["tool_calls"] == 0

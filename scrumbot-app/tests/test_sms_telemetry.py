"""Telemetry wiring for the SMS handler: root span, flush ordering, attributes."""

import pytest

from functions.sms import handler as sms_handler


class _Ctx:
    """Minimal Lambda context for Powertools' inject_lambda_context."""
    function_name = "stride-sms"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:stride-sms"
    aws_request_id = "test-request-id"


class TestFlushOrdering:
    def test_flush_called_on_success(self, monkeypatch):
        calls = []
        monkeypatch.setattr(sms_handler, "flush", lambda *a, **k: calls.append("flush"))
        monkeypatch.setattr(sms_handler.app, "resolve", lambda e, c: {"statusCode": 200})

        assert sms_handler.handler({}, _Ctx()) == {"statusCode": 200}
        assert calls == ["flush"]

    def test_flush_called_when_resolve_raises(self, monkeypatch):
        """Telemetry must drain even on the error path, and must not swallow."""
        calls = []
        monkeypatch.setattr(sms_handler, "flush", lambda *a, **k: calls.append("flush"))

        def boom(event, context):
            raise RuntimeError("resolve exploded")

        monkeypatch.setattr(sms_handler.app, "resolve", boom)

        with pytest.raises(RuntimeError, match="resolve exploded"):
            sms_handler.handler({}, _Ctx())
        assert calls == ["flush"]

    def test_root_span_closes_before_flush(self, monkeypatch):
        """Flushing inside the span would leave the root span unexported."""
        order = []

        class _Span:
            def __enter__(self):
                order.append("span_open")
                return self

            def __exit__(self, *exc):
                order.append("span_close")
                return False

        class _Tracer:
            def start_as_current_span(self, name):
                order.append(f"start:{name}")
                return _Span()

        monkeypatch.setattr(sms_handler, "get_tracer", lambda: _Tracer())
        monkeypatch.setattr(sms_handler, "flush", lambda *a, **k: order.append("flush"))
        monkeypatch.setattr(sms_handler.app, "resolve", lambda e, c: {"statusCode": 200})

        sms_handler.handler({}, _Ctx())

        assert order == [
            "start:stride.sms.turn", "span_open", "span_close", "flush",
        ]


def _make_result(input_tokens=10, output_tokens=5, cycles=1):
    """Stand-in for a Strands AgentResult."""

    class _Result:
        class metrics:
            accumulated_usage = {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
            }

            @staticmethod
            def get_summary():
                return {"total_cycles": cycles}

        def __str__(self):
            return "hello from stride"

    return _Result()


def _fake_agent_class(captured, result):
    """Build a fake Agent that records constructor kwargs.

    MUST expose `.messages` — _call_agent passes `agent.messages` to
    save_conversation, and that attribute access happens even when
    save_conversation itself is patched out.
    """

    class _FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = []

        def __call__(self, message):
            return result

    return _FakeAgent


class TestAgentTraceAttributes:
    def test_agent_receives_trace_attributes(self, monkeypatch, ddb, seeded_user):
        """Both _call_agent call sites must tag spans with user + prompt version."""
        from shared.prompt import PROMPT_VERSION

        captured = {}
        monkeypatch.setattr(
            sms_handler, "Agent", _fake_agent_class(captured, _make_result())
        )
        monkeypatch.setattr(sms_handler, "save_conversation", lambda *a, **k: None)
        monkeypatch.setattr(sms_handler, "get_conversation", lambda uid: [])

        reply = sms_handler._call_agent(
            user_id=seeded_user, message="hi", is_new_user=False,
            user={"planning_day": 1, "timezone": "America/New_York"},
        )

        assert reply == "hello from stride"
        attrs = captured["trace_attributes"]
        assert attrs["user.id"] == seeded_user
        assert attrs["prompt_version"] == PROMPT_VERSION

    def test_cost_attributes_land_on_the_root_span(self, monkeypatch, ddb, seeded_user):
        """Proves the spec §3 claim: Strands never makes its spans ambient, so
        get_current_span() inside _call_agent is still OUR root span."""
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        from shared import telemetry

        result = _make_result(input_tokens=100, output_tokens=50, cycles=2)
        monkeypatch.setattr(sms_handler, "Agent", _fake_agent_class({}, result))
        monkeypatch.setattr(sms_handler, "save_conversation", lambda *a, **k: None)
        monkeypatch.setattr(sms_handler, "get_conversation", lambda uid: [])

        exporter = InMemorySpanExporter()
        provider = telemetry._build_provider("probe", exporter=exporter)

        with provider.get_tracer("stride").start_as_current_span("stride.sms.turn"):
            sms_handler._call_agent(
                user_id=seeded_user, message="hi", is_new_user=False,
                user={"planning_day": 1, "timezone": "America/New_York"},
            )
        provider.force_flush()

        span = exporter.get_finished_spans()[0]
        assert span.name == "stride.sms.turn"
        assert span.attributes["reply_length"] == len("hello from stride")
        assert span.attributes["agent.cycles"] == 2
        assert span.attributes["is_new_user"] is False
        # (100*3 + 50*15) / 1e6 = 0.00105
        assert span.attributes["estimated_cost_usd"] == pytest.approx(0.00105)

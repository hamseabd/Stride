"""Telemetry wiring for the scheduler Lambda: root span + flush on every exit path."""

import pytest

from functions.scheduler import handler as sched_handler


class _Ctx:
    """Minimal Lambda context for Powertools' inject_lambda_context."""
    function_name = "stride-scheduler"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:stride-scheduler"
    aws_request_id = "test-request-id"


def test_flush_called_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr(sched_handler, "flush", lambda *a, **k: calls.append("flush"))
    monkeypatch.setattr(sched_handler, "get_consented_users", lambda: [])

    result = sched_handler.handler({}, _Ctx())

    assert result == {"statusCode": 200, "processed": 0}
    assert calls == ["flush"]


def test_flush_called_when_user_scan_raises(monkeypatch):
    """get_consented_users() runs outside the per-user try/except, so a failure
    there propagates. Telemetry must still drain, and the error must not be swallowed."""
    calls = []
    monkeypatch.setattr(sched_handler, "flush", lambda *a, **k: calls.append("flush"))

    def boom():
        raise RuntimeError("scan failed")

    monkeypatch.setattr(sched_handler, "get_consented_users", boom)

    with pytest.raises(RuntimeError, match="scan failed"):
        sched_handler.handler({}, _Ctx())
    assert calls == ["flush"]


def test_root_span_mirrors_scheduler_metrics(monkeypatch):
    """The root span carries the same four fields as the scheduler_metrics log line."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    monkeypatch.setattr(sched_handler, "get_tracer", lambda: provider.get_tracer("test"))
    monkeypatch.setattr(sched_handler, "flush", lambda *a, **k: None)
    monkeypatch.setattr(sched_handler, "get_consented_users",
                        lambda: ["+15550000001", "+15550000002", "+15550000003"])

    def fake_process(user_id):
        if user_id.endswith("3"):
            raise RuntimeError("send failed")
        return user_id.endswith("1")

    monkeypatch.setattr(sched_handler, "_process_user", fake_process)

    sched_handler.handler({}, _Ctx())

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["stride.scheduler.run"]
    attrs = spans[0].attributes
    assert attrs["users_processed"] == 3
    assert attrs["sent_count"] == 1
    assert attrs["error_count"] == 1
    assert attrs["run_duration_ms"] >= 0

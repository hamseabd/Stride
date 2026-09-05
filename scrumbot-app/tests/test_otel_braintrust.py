"""Braintrust attribute remapping — active only when OTEL_VENDOR=braintrust."""

import json

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared import telemetry
from shared.otel_braintrust import BraintrustSpanExporter


def _span_with(attrs, name="Model invoke"):
    exporter = InMemorySpanExporter()
    provider = telemetry._build_provider("probe", exporter=exporter)
    with provider.get_tracer("t").start_as_current_span(name) as span:
        for key, value in attrs.items():
            span.set_attribute(key, value)
    provider.force_flush()
    return exporter.get_finished_spans()[0]


class TestBraintrustRemap:
    def test_prompt_and_completion_become_json_fields(self):
        inner = InMemorySpanExporter()
        exporter = BraintrustSpanExporter(inner, model_id="claude-sonnet-4-6")
        span = _span_with({
            "gen_ai.prompt": json.dumps([{"role": "user", "content": "hi"}]),
            "gen_ai.completion": json.dumps([{"role": "assistant", "content": "hey"}]),
            "gen_ai.usage.prompt_tokens": 10,
            "gen_ai.usage.completion_tokens": 4,
        })

        exporter.export([span])
        out = inner.get_finished_spans()[0].attributes

        assert json.loads(out["braintrust.input_json"]) == [{"role": "user", "content": "hi"}]
        assert json.loads(out["braintrust.output_json"]) == [{"role": "assistant", "content": "hey"}]
        assert json.loads(out["braintrust.metrics"]) == {
            "prompt_tokens": 10, "completion_tokens": 4,
        }

    def test_model_id_copied_onto_span_with_tokens(self):
        inner = InMemorySpanExporter()
        exporter = BraintrustSpanExporter(inner, model_id="claude-sonnet-4-6")
        span = _span_with({"gen_ai.usage.prompt_tokens": 1})

        exporter.export([span])
        assert inner.get_finished_spans()[0].attributes["gen_ai.request.model"] == "claude-sonnet-4-6"

    def test_original_attributes_preserved(self):
        inner = InMemorySpanExporter()
        exporter = BraintrustSpanExporter(inner)
        span = _span_with({"tool.name": "create_task"})

        exporter.export([span])
        assert inner.get_finished_spans()[0].attributes["tool.name"] == "create_task"

    def test_span_without_genai_attrs_passes_through_unchanged(self):
        inner = InMemorySpanExporter()
        exporter = BraintrustSpanExporter(inner)
        span = _span_with({"user.id": "+15551234567"}, name="stride.sms.turn")

        exporter.export([span])
        out = inner.get_finished_spans()[0].attributes
        assert out["user.id"] == "+15551234567"
        assert "braintrust.input_json" not in out
        assert "braintrust.output_json" not in out
        assert "braintrust.metrics" not in out

    def test_span_fields_survive_remapping(self, monkeypatch):
        """A dropped parent would silently flatten the trace tree — guard it."""
        monkeypatch.delenv("OTEL_VENDOR", raising=False)

        capture = InMemorySpanExporter()
        provider = telemetry._build_provider("probe", exporter=capture)
        tracer = provider.get_tracer("t")
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child") as child:
                child.set_attribute("gen_ai.usage.prompt_tokens", 7)
        provider.force_flush()

        finished = {s.name: s for s in capture.get_finished_spans()}
        original = finished["child"]

        inner = InMemorySpanExporter()
        BraintrustSpanExporter(inner, model_id="claude-sonnet-4-6").export([original])
        out = inner.get_finished_spans()[0]

        assert out.name == "child"
        assert out.parent is not None, "parent was dropped — trace tree would flatten"
        assert out.parent.span_id == finished["root"].context.span_id
        assert out.context.span_id == original.context.span_id
        assert out.start_time == original.start_time
        assert out.end_time == original.end_time
        assert out.resource is original.resource


class TestVendorGate:
    def test_not_applied_when_vendor_unset(self, monkeypatch):
        monkeypatch.delenv("OTEL_VENDOR", raising=False)
        inner = InMemorySpanExporter()
        assert telemetry._wrap_exporter(inner) is inner

    def test_applied_when_vendor_is_braintrust(self, monkeypatch):
        monkeypatch.setenv("OTEL_VENDOR", "braintrust")
        wrapped = telemetry._wrap_exporter(InMemorySpanExporter())
        assert isinstance(wrapped, BraintrustSpanExporter)

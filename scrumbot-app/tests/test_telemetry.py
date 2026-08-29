"""Tests for shared/telemetry.py — OTel setup, inertness, and flush safety."""

import subprocess
import sys
import textwrap
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared import telemetry


class TestDisabledByDefault:
    def test_is_enabled_false_when_endpoint_unset(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert telemetry.is_enabled() is False

    def test_is_enabled_true_when_endpoint_set(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://example.test/otel")
        assert telemetry.is_enabled() is True

    def test_init_is_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setattr(telemetry, "_provider", None)
        telemetry.init_telemetry("stride-sms")
        assert telemetry._provider is None

    def test_get_tracer_is_usable_when_disabled(self, monkeypatch):
        """No provider set -> proxy tracer -> non-recording span. Must not raise."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        with telemetry.get_tracer().start_as_current_span("noop") as span:
            span.set_attribute("key", "value")

    def test_init_is_noop_when_already_initialised(self, monkeypatch):
        """The _provider guard, not just the is_enabled() short-circuit."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://example.test/otel")
        sentinel = object()
        monkeypatch.setattr(telemetry, "_provider", sentinel)
        telemetry.init_telemetry("stride-sms")
        assert telemetry._provider is sentinel


class TestBuildProvider:
    def test_exports_spans_with_resource_attributes(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "test")
        exporter = InMemorySpanExporter()
        provider = telemetry._build_provider("stride-probe", exporter=exporter)

        with provider.get_tracer("t").start_as_current_span("hello"):
            pass
        provider.force_flush()

        spans = exporter.get_finished_spans()
        assert [s.name for s in spans] == ["hello"]
        assert spans[0].resource.attributes["service.name"] == "stride-probe"
        assert spans[0].resource.attributes["deployment.environment"] == "test"

    def test_does_not_register_globally(self, monkeypatch):
        """_build_provider is a pure constructor — the global must be untouched."""
        from opentelemetry import trace

        before = trace.get_tracer_provider()
        telemetry._build_provider("stride-probe", exporter=InMemorySpanExporter())
        assert trace.get_tracer_provider() is before


class TestFlush:
    def test_flush_noop_when_no_provider(self, monkeypatch):
        monkeypatch.setattr(telemetry, "_provider", None)
        telemetry.flush()

    def test_flush_never_raises(self, monkeypatch):
        class Exploding:
            def force_flush(self, timeout_millis=None):
                raise RuntimeError("network down")

        monkeypatch.setattr(telemetry, "_provider", Exploding())
        telemetry.flush()  # must swallow

    def test_flush_passes_timeout(self, monkeypatch):
        seen = {}

        class Recording:
            def force_flush(self, timeout_millis=None):
                seen["timeout"] = timeout_millis

        monkeypatch.setattr(telemetry, "_provider", Recording())
        telemetry.flush(timeout_millis=1234)
        assert seen["timeout"] == 1234


_APP_ROOT = Path(__file__).resolve().parents[1]

_PROVIDER_OWNERSHIP_PROBE = textwrap.dedent("""
    import sys
    # Endpoint must be set or Strands leaves its tracer as None and emits nothing.
    import os
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    # We go first.
    provider = TracerProvider(resource=Resource.create({"service.name": "stride-sms"}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stdout)))
    trace.set_tracer_provider(provider)

    # Strands initialises second and tries to override.
    from strands.telemetry.tracer import get_tracer as strands_get_tracer
    st = strands_get_tracer()

    assert trace.get_tracer_provider() is provider, "Strands replaced the global provider"
    assert st.tracer_provider is not provider, "expected Strands to build its own orphan provider"
    assert st.tracer is not None, "Strands tracer did not initialise"

    span = st.start_agent_span(prompt="hi", agent_name="probe-span", model_id="claude-sonnet-4-6")
    span.end()
    provider.force_flush()
""")


class TestProviderOwnership:
    def test_our_provider_wins_and_strands_spans_route_through_it(self):
        result = subprocess.run(
            [sys.executable, "-c", _PROVIDER_OWNERSHIP_PROBE],
            cwd=_APP_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"probe failed:\n{result.stderr}"
        # The span was created by Strands' tracer but printed by OUR exporter.
        assert "probe-span" in result.stdout
        assert '"service.name": "stride-sms"' in result.stdout


class TestSpanNesting:
    def test_strands_agent_span_parents_under_our_root(self):
        from strands.telemetry.tracer import Tracer as StrandsTracer

        exporter = InMemorySpanExporter()
        provider = telemetry._build_provider("stride-probe", exporter=exporter)

        # Strands with no endpoint leaves tracer None; point it at our provider
        # to isolate the parenting mechanic without any network or LLM call.
        st = StrandsTracer()
        st.tracer_provider = provider
        st.tracer = provider.get_tracer("strands")

        with provider.get_tracer("stride").start_as_current_span("stride.sms.turn"):
            agent_span = st.start_agent_span(
                prompt="hi", agent_name="Stride Agent", model_id="claude-sonnet-4-6"
            )
            agent_span.end()
        provider.force_flush()

        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert "Stride Agent" in spans, f"got {list(spans)}"
        assert spans["Stride Agent"].parent is not None, "agent span became a root"
        assert spans["Stride Agent"].parent.span_id == spans["stride.sms.turn"].context.span_id

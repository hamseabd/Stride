"""Tests for shared/telemetry.py — OTel setup, inertness, and flush safety."""

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

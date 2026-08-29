"""OpenTelemetry tracing setup for Stride Lambdas.

The destination is configured entirely through the standard OTLP environment
variables, so switching vendors never requires a code change:

    OTEL_EXPORTER_OTLP_ENDPOINT  https://api.braintrust.dev/otel
    OTEL_EXPORTER_OTLP_HEADERS   Authorization=Bearer <key>, x-bt-parent=project_id:<id>

    OTEL_EXPORTER_OTLP_ENDPOINT  https://<env>.live.dynatrace.com/api/v2/otlp
    OTEL_EXPORTER_OTLP_HEADERS   Authorization=Api-Token <token>

When OTEL_EXPORTER_OTLP_ENDPOINT is unset, every function here is inert and
no spans are produced.

Call init_telemetry() early in the handler, before constructing any Agent.
Strands' own tracer calls trace.set_tracer_provider() too, but that call is
latched to the first caller. By initializing our provider first, Strands'
provider is discarded and its tracer resolves against ours, so its spans
inherit our resource attributes and flush control.
"""

import os

from aws_lambda_powertools import Logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

logger = Logger()

_provider: TracerProvider | None = None


def is_enabled() -> bool:
    """True when an OTLP endpoint is configured."""
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _wrap_exporter(exporter: SpanExporter) -> SpanExporter:
    """Apply vendor-specific attribute mapping when OTEL_VENDOR requests it."""
    if os.getenv("OTEL_VENDOR", "").lower() == "braintrust":
        from shared.otel_braintrust import BraintrustSpanExporter
        return BraintrustSpanExporter(exporter, model_id=os.getenv("OTEL_MODEL_ID"))
    return exporter


def _build_provider(service_name: str, exporter: SpanExporter | None = None) -> TracerProvider:
    """Build a configured TracerProvider WITHOUT registering it globally.

    Test seam: trace.set_tracer_provider() only succeeds once per process, so
    tests exercise this instead of init_telemetry() to avoid fighting the latch.

    The exporter takes no arguments on purpose — OTLPSpanExporter natively reads
    OTEL_EXPORTER_OTLP_ENDPOINT (appending /v1/traces) and
    OTEL_EXPORTER_OTLP_HEADERS. Do not hand-parse either; that is what keeps
    both vendors' base URLs working unmodified.
    """
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": os.getenv("ENVIRONMENT", "local"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(_wrap_exporter(exporter or OTLPSpanExporter())))
    return provider


def init_telemetry(service_name: str) -> None:
    """Register the global TracerProvider. Idempotent. No-op when disabled."""
    global _provider
    if _provider is not None or not is_enabled():
        return
    try:
        provider = _build_provider(service_name)
        trace.set_tracer_provider(provider)
        _provider = provider
        logger.info("otel_initialized", service_name=service_name)
    except Exception:
        _provider = None
        logger.exception("otel_init_failed")


def get_tracer() -> trace.Tracer:
    """Always usable. Returns a no-op proxy tracer when telemetry is disabled.

    This is why no caller needs an `if enabled:` branch.
    """
    return trace.get_tracer("stride")


def flush(timeout_millis: int = 2000) -> None:
    """Drain pending spans before Lambda freezes the environment. Never raises."""
    if _provider is None:
        return
    try:
        _provider.force_flush(timeout_millis=timeout_millis)
    except Exception:
        logger.warning("otel_flush_failed")

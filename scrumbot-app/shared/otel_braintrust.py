"""Braintrust-specific OTel attribute remapping.

Strands emits gen_ai.prompt / gen_ai.completion as single JSON strings, but
Braintrust renders input/output from `gen_ai.prompt.N.content` or `*_json`
fields. Without this wrapper Braintrust still ingests the spans and draws the
waterfall, but the input/output panes stay empty and cost is not computed.

Strands also sets gen_ai.request.model only on the agent span, while the
tokens live on the model-invoke span. Braintrust needs both together to price
a call, so we stamp the model onto any span carrying usage.

Kept behind OTEL_VENDOR=braintrust so the vendor-neutral path stays clean.
"""

import json

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class BraintrustSpanExporter(SpanExporter):
    """Wraps another exporter, remapping gen_ai.* attributes to braintrust.*."""

    def __init__(self, inner: SpanExporter, model_id: str | None = None):
        self._inner = inner
        self._model_id = model_id

    def export(self, spans) -> SpanExportResult:
        return self._inner.export([self._remap(s) for s in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)

    def _remap(self, span: ReadableSpan) -> ReadableSpan:
        attrs = dict(span.attributes or {})

        if "gen_ai.prompt" in attrs:
            attrs["braintrust.input_json"] = attrs["gen_ai.prompt"]
        if "gen_ai.completion" in attrs:
            attrs["braintrust.output_json"] = attrs["gen_ai.completion"]

        metrics = {}
        if "gen_ai.usage.prompt_tokens" in attrs:
            metrics["prompt_tokens"] = attrs["gen_ai.usage.prompt_tokens"]
        if "gen_ai.usage.completion_tokens" in attrs:
            metrics["completion_tokens"] = attrs["gen_ai.usage.completion_tokens"]
        if metrics:
            attrs["braintrust.metrics"] = json.dumps(metrics)
            if self._model_id and "gen_ai.request.model" not in attrs:
                attrs["gen_ai.request.model"] = self._model_id

        # ReadableSpan.attributes is immutable — rebuild rather than mutate.
        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=attrs,
            events=span.events,
            links=span.links,
            status=span.status,
            kind=span.kind,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )

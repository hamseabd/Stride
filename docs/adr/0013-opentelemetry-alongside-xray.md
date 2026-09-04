# 0013. OpenTelemetry Alongside X-Ray

Date: 2026-08-29 · Status: Accepted

## Context

AWS X-Ray shows Lambda cold start, warm latency, and external service calls, but does not instrument the agent's internal loops, tool invocations, or token consumption. Understanding what Strands is doing inside the turn requires deeper visibility.

## Decision

Register Stride's own `TracerProvider` at handler import, before Strands constructs its tracer. Strands' later `set_tracer_provider` call is ignored, so its agent, cycle, model and tool spans route through Stride's exporter. Open one root span per turn (`stride.sms.turn`, `stride.scheduler.run`) and a child span around the classifier. Instrument botocore so DynamoDB calls nest under the tool that made them. The destination is whatever the standard OTLP environment variables name; an optional vendor flag remaps `gen_ai` attributes for Braintrust. With no endpoint set, every call is a no-op.

## Consequences

Spans carry full prompts and completions, so enabling export sends conversation content to the trace vendor. That is deliberate and documented in the app's conventions: it is what makes conversation-level debugging and production-traces-to-evals possible, and the privacy policy must name the vendor before real user traffic is exported. X-Ray stays on for both Lambdas until OpenTelemetry has been proven in production; removing it is a separate decision. Local runs can capture the same spans in memory (`chat.py --trace`) without any vendor.

# 0013. OpenTelemetry Alongside X-Ray

Date: 2026-08-29 · Status: Accepted

## Context

AWS X-Ray shows Lambda cold start, warm latency, and external service calls, but does not instrument the agent's internal loops, tool invocations, or token consumption. Understanding what Strands is doing inside the turn requires deeper visibility.

## Decision

Register a `TracerProvider` before Strands initializes its own. Root span per turn, with child spans for context assembly, classification, and each tool invocation. Instrument botocore so DynamoDB calls nest under their tool spans. Telemetry destination is optional: standard OTLP environment variables. When set, a Braintrust destination is remapped to avoid full-prompt export by default. When unset, tracing is inert.

## Consequences

Full prompts leave the account only when the user explicitly enables export. X-Ray remains the primary production telemetry; OTel is a development and audit tool until proven in beta. The trace tree shows every tool cycle and its latency. Span names include the tool function name and the turn intent. Adding OTel increased Lambda package size by ~2 MB; startup latency is negligible.

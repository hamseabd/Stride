# Changelog

## v2.3 — 2026-09-04
- Security: tools act on the server-bound user, never on a model-supplied id (BUG-002).
- OpenTelemetry tracing for both Lambdas, inert unless an OTLP endpoint is set; Strands and DynamoDB spans nest under a root span per turn.
- `chat.py` runs on moto by default; scripted sessions, per-turn records, span capture.
- CI: unit tests and L1 evals gate the deploy; nightly judge can reach Bedrock.
- Docs: ADRs, threat model, prompt design, data model, annotated transcript, trace waterfall, retrospective.

## v2.2 — 2026-06-28
- Eval suite: L1 deterministic assertions on every PR, L2 LLM-as-judge nightly on a cross-family model (Amazon Nova Pro), regression tests for fixed bugs.
- Jargon validator widened; CI builds ARM64 images with QEMU; README rewritten for the public repo.

## v2.1 — 2026-04-03
- Onboarding overhaul: adaptive flow, multi-goal capture, graceful handling of over-long messages.
- `resolve_date` and `archive_project` tools; past-date validation.
- Mobile-first landing page.

## v2.0 — 2026-04-02
- Prompt and flow revision: timezone inferred from area code, session-aware context for replies to proactive messages, on-demand goal decomposition.

## v1.1 — 2026-03-28
- Coaching tone overhaul: tone derived from reply behaviour, planning as a conversation, Friday review made actionable.
- Beta-ready: A2P 10DLC approved, legal pages published.

## v1.0 — 2026-03-05
- Inbound SMS agent with consent flow, 19 tools, single-table DynamoDB, Lambda container images on ARM64.
- Proactive scheduler: morning reminder, evening check-in, planning day, midweek adjust, Friday review.

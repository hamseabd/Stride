# Threat model

Stride handles real phone numbers, user goals, daily check-ins, consent state, and API keys. Threat vectors include forged requests, prompt injection, and unauthorized access. Security matters early because user trust compounds.

## Assets

- User phone numbers (E.164 format) and derived identities
- Personal productivity data: goals, projects, work estimates, daily check-ins
- Consent state: opt-in to messaging, proactive nudge preferences
- API keys (Anthropic, Twilio) and AWS credentials for Lambda execution
- Scheduled outbound message state in DynamoDB
- CI/CD secrets: GitHub Actions OIDC role and deployment credentials

## Entry points

- **Twilio webhook** (POST `/sms`): inbound SMS and message status callbacks
- **EventBridge timer** (every 15 minutes): proactive nudge scheduler
- **GitHub Actions**: CI/CD pipeline for Terraform and Lambda deployment

## Controls

| Threat | Control | Where | ADR |
|---|---|---|---|
| Forged webhook | Twilio signature validation, 403 on failure | `_validate_twilio` | — |
| Runaway cost | 50 msgs/day atomic counter (fails open); 20-turn history cap; 1,024 max output tokens; 480-char reply cap; 1,600-char input cap | guards, handler, validators | [ADR-0011](adr/0011-rate-limiter-fails-open.md) |
| Unsolicited messages (TCPA) | opt-in `YES`/`START` before any agent message; separate proactive consent; `STOP` exact match revokes both | handler, scheduler | — |
| Prompt injection → cross-tenant access | server-side tenant binding on user_id before passing to tools | `shared/tenant.py` | [ADR-0012](adr/0012-server-side-tenant-binding.md) |
| Jargon or over-long output | post-generation validator; L1 evals on every PR | validators, evals | — |
| Slow model reply | 12 s TwiML deadline, REST fallback | handler | [ADR-0010](adr/0010-twelve-second-reply-fallback.md) |
| DB outage | limiter fails open; classifier failure defaults to conversation; agent failure returns a fixed error reply | guards, handler | — |
| CI compromise | split OIDC roles; secrets only in Actions | infra | [ADR-0009](adr/0009-split-oidc-roles-for-ci.md) |
| Secrets in repo | `.env`, `terraform.tfvars` ignored; hygiene test scans public files | tests | — |

## Known gaps

- **ID-keyed tools not tenant-bound**: tools taking only user_id do not re-validate tenant membership; accepted because tools run in the Lambda sandbox.
- **OTel spans carry full prompts**: OpenTelemetry tracing logs complete prompts in spans; accepted because OTel is disabled by default and used only for development.
- **No per-user cost alarm**: the system does not alert on daily LLM spend thresholds; accepted because cost-per-user is under $0.01/day.
- **Rate limit is per day, not per minute**: the 50-message counter is atomic but not instantaneous; accepted because solo devs and founders do not send bot-like bursts.

## What is not in scope

- **DDoS at the Twilio or API Gateway layer**: Twilio's infrastructure and AWS API Gateway rate limiting are outside our control; this threat is assumed to be mitigated by the platform.
- **Physical device compromise**: if a user's phone is compromised, an attacker has access to all Stride messages and can reply as the user; this is a device-level threat that no SaaS backend can prevent.
- **Anthropic or AWS provider-side failures**: loss of service, data breach, or compromise of the LLM or cloud provider infrastructure is assumed to be handled by the provider's security controls and is not audited in this model.

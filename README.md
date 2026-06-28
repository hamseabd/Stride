# Stride

**An AI productivity coach that lives in your texts.** No app, no login, no dashboard — Stride texts *you*, you text back, and it keeps you honest about what you said you'd finish.

Most productivity tools wait to be opened. Stride pushes first: a daily check-in, a weekly review, a nudge when you've over-committed. The agile machinery underneath (estimates, cycles, velocity, pattern detection) never surfaces — users only ever see plain language.

> Built solo, deployed on AWS, dogfooded daily. This repo is the whole thing: the agent, the infrastructure, and the eval suite that keeps it from regressing.

---

## Why it's interesting

- **Push, not pull.** A scheduler Lambda decides when to reach out — the proactive message *is* the product. A to-do app doesn't know you; Stride accrues a per-user pattern record (where you overcommit, what you underestimate, what stays blocked) and adapts its tone and timing.
- **Two Lambdas, one table.** Everything runs on `stride-sms` (inbound) and `stride-scheduler` (outbound, every 15 min) over a single DynamoDB table. No relational sprawl, no second datastore.
- **Every inbound SMS clears a guard chain** — Twilio signature → rate limit → consent → intent classifier — before it ever reaches the model. TCPA consent and a 50-msg/day atomic counter are enforced, not aspirational.
- **The agent never improvises its tools.** All 21 tools are declared with the Strands SDK; context is pre-loaded before each turn, history is capped at 20 turns, and every reply is validated (length, jargon, PII) before it's sent.
- **Tested like production, judged like production.** 261 unit tests plus a three-tier eval suite — deterministic checks gate every PR; an LLM-as-judge (a *different* model family, to avoid a model grading itself) runs nightly.

---

## How it works

<p align="center">
  <img src="docs/assets/architecture.png" alt="Stride architecture — inbound SMS flows through stride-sms (guard chain → intent classifier → Strands agent); stride-scheduler pushes proactive SMS on a 15-minute EventBridge timer; both Lambdas share one DynamoDB table." width="900">
</p>

A first-time user is walked through setup; from then on the conversation flows through five session types:

| Session | What happens |
|---|---|
| **Set up** | Tell Stride what you're working on. It creates your projects and plans week one. |
| **Plan your week** | Commit to what's realistic. It challenges overcommitting and breaks big work down. |
| **Daily check-in** | Three fast questions: did / doing / blocked. |
| **Weekly review** | Planned vs. done — honest numbers, one pattern, one change. |
| **Adjust** | Add, drop, or re-estimate mid-week when reality shifts. |

Estimates stay human: **S** (a few hours) · **M** (a day or two) · **L** (most of the week) · **XL** (more than a week — flagged as scope risk).

---

## Stack

| | |
|---|---|
| **Agent** | Strands SDK · Claude Sonnet 4.6 via the Anthropic API |
| **Compute** | AWS Lambda · Python 3.12 · ARM64 (Graviton) · container images |
| **Data** | DynamoDB — single-table design, `PAY_PER_REQUEST` |
| **Messaging** | Twilio A2P 10DLC SMS |
| **IaC** | Terraform + serverless.tf modules · S3/DynamoDB remote state |
| **Observability** | AWS Lambda Powertools v3 — structured telemetry per call (tokens, latency, cost, cache hits) |
| **CI/CD** | GitHub Actions — OIDC auth (no long-lived keys), Docker build → `terraform apply` |

---

## Evals

Quality is enforced in CI, not vibes:

- **L1 — deterministic** (gates every PR, <5s, $0): length, jargon, PII, tool-arg correctness, onboarding order. These delegate to the *same* validator the production path runs, so a check can't pass in CI while drifting in prod.
- **L2 — LLM-as-judge** (nightly): tool selection and coaching tone, scored critique-then-verdict by a cross-family model to avoid self-preference bias.
- **Regression**: every fixed production bug becomes a permanent moto-backed test.

```bash
make eval-l1   # deterministic, no API key needed
make eval-l2   # nightly judge
```

---

## Run it locally

```bash
cp scrumbot-app/.env.example scrumbot-app/.env   # add your Anthropic key
make up                                          # LocalStack + DynamoDB + Flask, on http://localhost:8000
make test                                        # 261 tests
make chat                                         # interactive SMS simulator
```

The local image is the same Linux/ARM64 Python base as Lambda — no platform surprises.

## Deploy

```bash
cd scrumbot-infra/bootstrap && terraform init && terraform apply   # one-time: remote state
cp scrumbot-infra/terraform.tfvars.example scrumbot-infra/terraform.tfvars   # add secrets
make deploy                                                        # build → push → terraform apply
```

On push to `main`, CI builds SHA-tagged images and applies Terraform. Secrets (`AWS_ROLE_ARN`, `ANTHROPIC_API_KEY`, Twilio credentials) live in GitHub Actions — never in the repo.

---

## Repo layout

```
scrumbot-app/      Python — handlers (sms, scheduler), shared lib, tools, tests, evals
scrumbot-infra/    Terraform — Lambdas, API Gateway, DynamoDB, ECR, IAM, EventBridge
scripts/           build/push images, deploy the marketing site
docs/legal/        privacy policy + terms of service
```

The data model is one DynamoDB table; access patterns and the locked schema live in [`scrumbot-app/CLAUDE.md`](scrumbot-app/CLAUDE.md).

---

<sub>Personal project. Code is shared for reference; it targets one specific AWS account and Twilio number and isn't intended as a turnkey deploy.</sub>

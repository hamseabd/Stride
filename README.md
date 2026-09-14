# Stride

[![Deploy](https://github.com/hamseabd/Stride/actions/workflows/terraform.yml/badge.svg)](https://github.com/hamseabd/Stride/actions/workflows/terraform.yml)
[![L1 evals](https://github.com/hamseabd/Stride/actions/workflows/evals-l1.yml/badge.svg)](https://github.com/hamseabd/Stride/actions/workflows/evals-l1.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**An AI productivity coach that lives in your texts.** No app, no login, no dashboard. Stride texts first, you text back, and it keeps you honest about what you said you'd finish. The agile machinery underneath (estimates, cycles, velocity, pattern detection) never surfaces; users only ever see plain language.

- **Push, not pull.** A scheduler decides when to reach out. The nudge is the product.
- **Two Lambdas, one table.** An inbound agent, an outbound scheduler, a single DynamoDB table.
- **Guarded by default.** Signature, rate limit, consent and an intent classifier before the model. Server-side tenant binding on every tool call after it.
- **Tested like production.** 394 unit tests and a three-tier eval suite gate every deploy. A cross-family judge grades coaching tone nightly.

> Built solo, deployed on AWS, ran a six-user private beta in April 2026 and still runs today.

---

## See it work

<table>
<tr>
<td width="42%" valign="top">
<img src="docs/assets/transcript.svg" width="360" alt="First three turns of a real onboarding session over SMS: Stride's intro, Jordan describing his Chrome extension project, and Stride planning week one.">
</td>
<td valign="top">
<p><b>Three turns, from opt-in to a planned week.</b> Real model calls against the production prompt, tools and classifier; DynamoDB mocked in-process.</p>
<p><b>Turn 1</b> · Opt-in. No tool calls. The static prompt prefix is written to cache once. <code>$0.0389</code></p>
<p><b>Turn 2</b> · Jordan gives a name, a project and a deadline. <code>resolve_date</code> → <code>set_user_preference</code> → <code>create_project</code>. Prompt read from cache. <code>$0.0289</code></p>
<p><b>Turn 3</b> · Week one planned. <code>create_work_cycle</code> → <code>create_task</code> ×2 → <code>complete_onboarding</code>. <code>$0.0334</code></p>
<p>Full six-turn session with tokens, latency and tool arguments per turn: <a href="docs/examples/onboarding-session.md">docs/examples/onboarding-session.md</a>.</p>
<p>Generating this transcript surfaced two real bugs: ids missing from the pre-loaded context, and tool calls losing tenant binding on a thread pool. Both are fixed, and both are permanent regression tests (<a href="scrumbot-app/evals/regression/MANIFEST.md">BUG-003 / BUG-004</a>).</p>
<p>Run it yourself with <code>make chat</code>. It needs only an Anthropic key.</p>
</td>
</tr>
</table>

---

## Quick start

```bash
cp scrumbot-app/.env.example scrumbot-app/.env                  # add ANTHROPIC_API_KEY
make test                                                       # unit tests, no key needed
make chat                                                       # talk to the agent, DynamoDB mocked in-process
make chat ARGS="--script docs/examples/scripts/onboarding.txt"  # replay the documented session
```

Or open the repo in GitHub Codespaces; the devcontainer installs everything. For persistent state, `make up && make chat ARGS="--localstack"` runs the Flask API against LocalStack.

<details>
<summary><b>Deploy to your own AWS account</b></summary>

```bash
cd scrumbot-infra/bootstrap && terraform init && terraform apply           # one-time: remote state
cp scrumbot-infra/terraform.tfvars.example scrumbot-infra/terraform.tfvars  # add secrets
make deploy                                                                 # build → push → terraform apply
```

On push to `main`, CI runs the unit tests and L1 evals, builds SHA-tagged ARM64 images, and applies Terraform. Secrets (`AWS_ROLE_ARN`, `ANTHROPIC_API_KEY`, Twilio credentials) live in GitHub Actions, never in the repo. CI authenticates with OIDC; there are no long-lived keys ([ADR-0009](docs/adr/0009-split-oidc-roles-for-ci.md)).

</details>

---

## How it works

<p align="center">
  <img src="docs/assets/architecture.png" alt="Stride architecture: inbound SMS flows through stride-sms (guard chain, intent classifier, Strands agent); stride-scheduler pushes proactive SMS on a 15-minute EventBridge timer; both Lambdas share one DynamoDB table." width="900">
</p>

Every inbound message clears the guard chain and gets classified by Haiku. Only a coaching turn reaches the Sonnet agent, and it arrives with everything the agent needs already loaded:

```mermaid
sequenceDiagram
  participant T as Twilio
  participant H as stride-sms
  participant C as Haiku classifier
  participant A as Sonnet agent (Strands)
  participant D as DynamoDB
  T->>H: POST /sms (signed)
  H->>H: signature · length · rate limit · STOP · consent
  H->>C: classify(message)
  C-->>H: conversation | feedback | remind_me | no_reminders | help
  alt not a coaching turn
    H-->>T: canned reply (TwiML)
  else coaching turn
    H->>D: pre-load projects, tasks, habits, patterns, history
    H->>A: system = cached prefix + user context; bind_user(from)
    A->>D: tool calls (create_task, create_checkin, …)
    A-->>H: reply
    H->>H: validate (length, jargon, empty)
    alt under 12 s
      H-->>T: TwiML reply
    else slow
      H->>T: REST send, empty TwiML
    end
  end
```

The scheduler shares the table but never touches a model. Every 15 minutes it queries users with proactive consent, checks the local-time window and whether today's nudge already went out, renders a message from stored data, and sends it over Twilio REST. 14,004 runs so far, zero errors, zero LLM cost ([ADR-0006](docs/adr/0006-scheduler-never-calls-an-llm.md)).

A first-time user is walked through setup. From then on the conversation moves through five session types:

| Session | What happens |
|---|---|
| **Set up** | Tell Stride what you're working on. It creates your projects and plans week one. |
| **Plan your week** | Commit to what's realistic. It challenges overcommitting and breaks big work down. |
| **Daily check-in** | Three fast questions: did / doing / blocked. |
| **Weekly review** | Planned vs. done. Honest numbers, one pattern, one change. |
| **Adjust** | Add, drop, or re-estimate mid-week when reality shifts. |

Estimates stay human: **S** a few hours · **M** a day or two · **L** most of the week · **XL** more than a week, flagged as scope risk.

---

## Design decisions

- **Haiku classifies intent before Sonnet sees a message.** Routing non-coaching turns away drops cost from ~$0.019 to ~$0.0003 per message. [ADR-0003](docs/adr/0003-haiku-classifier-in-front-of-sonnet.md)
- **The handler preloads all context; the agent never fetches its own.** Projects, tasks, habits and patterns are assembled before the model is invoked, so behavior stays predictable and debuggable. [ADR-0004](docs/adr/0004-preload-context-never-let-the-agent-fetch.md)
- **The scheduler never calls an LLM.** Proactive nudges are template-rendered Python, so 14,004 runs cost nothing beyond the SMS segment. [ADR-0006](docs/adr/0006-scheduler-never-calls-an-llm.md)
- **The eval judge is a different model family than the agent.** Amazon Nova Pro grades Sonnet's output, avoiding the self-preference bias a same-family judge carries. [ADR-0007](docs/adr/0007-cross-family-llm-judge.md)
- **The system prompt splits into a cached static prefix and an uncached per-user suffix.** This held cache reuse at 73% of prompt tokens across the beta. [ADR-0008](docs/adr/0008-prompt-layering-for-cache-stability.md)
- **Every agent turn is bound server-side to the authenticated phone number.** A prompt-injected `user_id` in a tool call is checked against the real sender, not trusted. [ADR-0012](docs/adr/0012-server-side-tenant-binding.md)

All thirteen records: [docs/adr](docs/adr/README.md).

---

## Production numbers

Six users, one month, no cherry-picking. Small numbers, real ones:

| Metric | Value |
|---|---|
| Beta window | April 2026, 6 users (owner + friends) |
| Coached turns (Sonnet) | 46 |
| Proactive nudges sent | 31 (morning 14 · evening 9 · planning 5 · midweek 4 · review 4) |
| Scheduler runs | 14,004 with 0 errors, avg 1.0 s |
| Avg agent latency | 2,862 ms (max 20,044 ms) |
| Cache share of prompt tokens | ≈73% |
| Avg cost per coached turn | $0.0191 |
| Total LLM spend, whole beta | $0.90 |

Unit economics, one assumption stated: a user who takes one coached turn per weekday plus the five weekly nudges costs about $0.40 in LLM and $0.30 in SMS per month. Under $1, against a $15/mo price.

---

## Quality

**Evals run in CI, not on vibes.**

| Tier | Runs | Checks |
|---|---|---|
| **L1 deterministic** | every PR, under 5 s, $0 | Length, jargon, PII, tool-arg correctness, onboarding order. Delegates to the same validator the production path runs, so a check can't pass in CI while drifting in prod. |
| **L2 LLM-as-judge** | nightly | Tool selection and coaching tone, critique-then-verdict, scored by Amazon Nova Pro so the agent's own model family never grades it. |
| **Regression** | every PR | Every fixed production bug, as a moto-backed test. [MANIFEST](scrumbot-app/evals/regression/MANIFEST.md) |

The nightly run is red on purpose. The judge passes; the classifier-recall check does not. Haiku scores 88% on the `feedback` and `remind_me` intents against a 95% bar (8 fixtures each), and it stays red until the classifier prompt is fixed. An eval that names the gap is doing its job.

```bash
make eval-l1   # deterministic, no API key needed
make eval-l2   # nightly judge, needs Bedrock access
```

**Every call leaves a trace.** Agent, classifier and scheduler calls emit structured Powertools events (`agent_metrics`, `classifier_metrics`, `scheduler_metrics`, `validation_warning`) to CloudWatch, and X-Ray traces both Lambdas. OpenTelemetry sits alongside X-Ray: each turn opens one root span, Strands' own agent, cycle, model and tool spans nest underneath it, and the whole thing is a no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Point it at any OTLP backend without a code change ([ADR-0013](docs/adr/0013-opentelemetry-alongside-xray.md)).

<p align="center">
  <img src="docs/assets/trace-waterfall.svg" alt="Waterfall of one SMS turn: six model cycles under one Strands Agent span, with seven tool calls (set_user_preference, resolve_date, create_project, create_work_cycle, two create_task calls, complete_onboarding), DynamoDB reads before the agent and writes after it." width="900">
</p>

<sub>One real turn, captured locally with <code>chat.py --trace</code>: seven tool calls across six model cycles while onboarding and planning week one. 36 spans, 17.5 s.</sub>

**Failure modes have owners.** Forged webhooks, prompt injection reaching for another user's data, runaway cost from a stuck loop, unsolicited messages under TCPA, a slow model against Twilio's 15-second deadline. Each has a control, each control has an owner in the code, and the known gaps are listed alongside them in [docs/threat-model.md](docs/threat-model.md).

---

## Stack

| Layer | Choice |
|---|---|
| **Agent** | Strands SDK · Claude Sonnet 4.6 via the Anthropic API |
| **Classifier** | Claude Haiku 4.5, intent only |
| **Compute** | AWS Lambda · Python 3.12 · ARM64 (Graviton) · container images |
| **Data** | DynamoDB, single-table design, `PAY_PER_REQUEST` |
| **Messaging** | Twilio A2P 10DLC SMS |
| **IaC** | Terraform + serverless.tf modules · S3/DynamoDB remote state |
| **Observability** | AWS Lambda Powertools v3 · X-Ray · OpenTelemetry (inert by default) |
| **CI/CD** | GitHub Actions · OIDC auth · tests and L1 evals gate `terraform apply` |

---

## Where to look

| File | What it holds |
|---|---|
| [`functions/sms/handler.py`](scrumbot-app/functions/sms/handler.py) | The guard chain and everything between a webhook and the agent |
| [`shared/tools.py`](scrumbot-app/shared/tools.py) | The 21 tools the agent can call |
| [`shared/tenant.py`](scrumbot-app/shared/tenant.py) | Server-side tenant binding |
| [`shared/prompt.py`](scrumbot-app/shared/prompt.py) | The layered system prompt; see [docs/prompt-design.md](docs/prompt-design.md) |
| [`shared/telemetry.py`](scrumbot-app/shared/telemetry.py) | The OpenTelemetry wiring, inert by default |
| [`evals/l2/judge.py`](scrumbot-app/evals/l2/judge.py) | The cross-family LLM judge |

```
scrumbot-app/      Python: handlers (sms, scheduler), shared lib, tools, tests, evals
scrumbot-infra/    Terraform: Lambdas, API Gateway, DynamoDB, ECR, IAM, EventBridge
scripts/           build/push images, deploy the marketing site, render docs assets
docs/adr/          13 architecture decision records
docs/examples/     annotated transcript + the script that generates it
docs/legal/        privacy policy + terms of service
.devcontainer/     Codespaces / VS Code container definition
```

The data model is one DynamoDB table. Access patterns and the locked schema live in [docs/data-model.md](docs/data-model.md). The unit suite includes a repo-hygiene test that scans every tracked file for banned jargon and stray phone numbers.

---

## What I'd do differently

I'd schedule a security review of tool inputs on day three, not five months in. The tenant-binding gap was a lucky catch, not a designed-in control. I'd also alert on the first eval failure instead of trusting a badge; a nightly suite ran red for 60 runs before anyone noticed. Full list: [docs/retrospective.md](docs/retrospective.md).

---

<sub>Personal project. Code is shared for reference; it targets one specific AWS account and Twilio number and isn't intended as a turnkey deploy.</sub>

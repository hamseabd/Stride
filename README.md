# Stride

An AI productivity coach delivered via SMS. Text your goals, check in daily, review your week. No app. No login. No dashboard. Just your phone.

The Scrum framework runs entirely under the hood — users never see it. Plain language only.

---

## How it works

Text Stride's number. It walks you through 5 types of sessions:

| Session | What happens |
|---|---|
| **Get set up** | First time only. Tell Stride what you're working on. It creates your projects and plans your first week. |
| **Plan your week** | Commit to what's realistic. Stride challenges overcommitting and breaks big things down. |
| **Daily check-in** | 3 questions fast: what did you do, what are you doing today, anything blocking you? |
| **Weekly review** | Planned vs done. Honest numbers. One pattern. One change. |
| **Adjust your plan** | Add tasks, drop tasks, re-estimate when things change mid-week. |

**Estimates:** S (a few hours), M (a day or two), L (most of the week), XL (more than a week — Stride flags this as risky).

---

## Architecture

```
SMS → Twilio → POST /sms → stride-sms Lambda
                              ↓
                         Guard chain (signature, rate limit, consent)
                              ↓
                         Strands Agent (Claude claude-sonnet-4-6)
                              ↓
                         13 tools → DynamoDB (stride-prod)
```

| Component | Choice |
|---|---|
| Compute | AWS Lambda Python 3.12, ARM64 (Graviton) |
| Database | DynamoDB — single-table design |
| Agent | Strands SDK + Claude claude-sonnet-4-6 via Anthropic API |
| Messaging | Twilio A2P 10DLC SMS |
| IaC | Terraform + serverless.tf modules |
| Observability | AWS Lambda Powertools v3 (structured logging, X-Ray tracing) |
| Deploy | Lambda container images pushed to ECR |
| CI/CD | GitHub Actions — OIDC auth, Docker build + Terraform apply |

---

## Repo structure

```
ScrumAgent/
├── scrumbot-app/           # Python application code
│   ├── functions/
│   │   ├── checkin/        # POST /checkin — direct tool calls
│   │   ├── agent/          # POST /ceremony — Strands conversational agent
│   │   └── sms/            # POST /sms — Twilio webhook + full guard chain
│   ├── shared/
│   │   ├── tools.py        # 13 Strands @tool functions
│   │   ├── db.py           # DynamoDB client, consent, rate limit, user bootstrap
│   │   ├── models.py       # 8 Pydantic v2 models
│   │   ├── prompt.py       # STRIDE_SYSTEM_PROMPT — single source of truth
│   │   └── guards.py       # Message validation + rate limiting
│   ├── Dockerfile          # Production Lambda image (ARG FUNCTION=checkin|agent|sms)
│   └── Dockerfile.dev      # Local dev image (Flask, same base as Lambda)
├── scrumbot-infra/         # Terraform infrastructure
│   ├── bootstrap/          # One-time: S3 state bucket + DynamoDB lock table
│   ├── lambda.tf           # 3 Lambda functions (container image)
│   ├── api_gateway.tf      # HTTP API — 3 routes
│   ├── dynamodb.tf         # stride-prod table + GSI
│   ├── ecr.tf              # 3 ECR repos + lifecycle policies
│   ├── iam.tf              # Lambda exec role + ECR push policy
│   └── variables.tf        # image_tag, secrets, region, table name
├── scripts/
│   └── build_and_push.sh   # Build all 3 images (linux/arm64) + push to ECR
├── docker-compose.yml      # Local dev: LocalStack + DynamoDB init + Flask server
├── Makefile                # Developer shortcuts
└── docs/
    ├── status.md           # Project status tracker
    └── legal/              # Privacy policy + Terms of service
```

---

## Live endpoints

**API:** `https://cbkpntvax6.execute-api.us-east-1.amazonaws.com`

| Method | Path | Lambda | Purpose |
|---|---|---|---|
| POST | `/checkin` | `stride-checkin` | Daily check-in |
| POST | `/ceremony` | `stride-agent` | Conversational session |
| POST | `/sms` | `stride-sms` | Twilio webhook |

---

## Local development

Prerequisites: Docker Desktop, AWS CLI (for LocalStack credential passthrough)

```bash
# Copy env template and fill in your Anthropic key
cp scrumbot-app/.env.example scrumbot-app/.env

# Start local stack — LocalStack + DynamoDB init + Flask dev server
make up
# API available at http://localhost:8000

# Stop and clean up volumes
make down
```

The local stack uses the same Linux ARM64 Python image as Lambda — no platform surprises.

---

## Deploy

Prerequisites: AWS CLI configured, Terraform installed, Docker Desktop running.

**First time only — bootstrap Terraform state:**
```bash
cd scrumbot-infra/bootstrap
terraform init && terraform apply
```

**Create secrets file:**
```bash
cp scrumbot-infra/terraform.tfvars.example scrumbot-infra/terraform.tfvars
# Fill in: anthropic_api_key, twilio_auth_token, twilio_account_sid, twilio_phone_number
```

**Build images + deploy infrastructure:**
```bash
make deploy
```

This runs `build_and_push.sh` (builds all 3 Lambda images for linux/arm64, pushes to ECR) then `terraform apply`.

**CI/CD:** On push to `main`, GitHub Actions builds images tagged `sha-{git_sha}`, then runs `terraform apply` with that tag. Requires `AWS_ROLE_ARN`, `ANTHROPIC_API_KEY`, `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_PHONE_NUMBER` as GitHub secrets.

---

## Twilio SMS setup

1. Buy a 10DLC phone number in the Twilio Console
2. Set the webhook URL: `{api_gateway_url}/sms` (HTTP POST)
3. Register an A2P 10DLC campaign (required for US SMS delivery)
4. Publish Privacy Policy and Terms of Service to a live URL (required for A2P registration)

Users opt in by replying YES to the first message. STOP unsubscribes immediately. 50 messages/day rate limit enforced per user.

---

## Makefile targets

```bash
make up          # Start local dev stack (docker compose up --build)
make down        # Stop and remove volumes
make build       # Build + push images tagged :latest
make push        # Build + push images tagged sha-{git short hash}
make deploy      # push + terraform apply
make logs-checkin  # Tail CloudWatch for stride-checkin
make logs-agent    # Tail CloudWatch for stride-agent
make logs-sms      # Tail CloudWatch for stride-sms
```

---

## DynamoDB single-table design

One table, no joins. All data accessed by `pk` + `sk` or via `gsi1`.

| Entity | PK | SK |
|---|---|---|
| User | `USER#{user_id}` | `#METADATA` |
| Project | `USER#{user_id}` | `PROJECT#{project_id}` |
| Work cycle | `PROJECT#{project_id}` | `CYCLE#{cycle_id}` |
| Task | `CYCLE#{cycle_id}` | `TASK#{task_id}` |
| Check-in | `USER#{user_id}` | `CHECKIN#{date}#{id}` |
| Blocker | `TASK#{task_id}` | `BLOCKER#{blocker_id}` |
| Velocity | `PROJECT#{project_id}` | `VELOCITY#{cycle_id}` |
| Pattern | `USER#{user_id}` | `PATTERN#AGGREGATE` |
| SMS consent | `USER#{user_id}` | `CONSENT#SMS` |
| Rate limit | `USER#{user_id}` | `RATELIMIT#{YYYY-MM-DD}` |
| Blocked log | `USER#{user_id}` | `BLOCKED#{iso_timestamp}` |

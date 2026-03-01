# Stride — Project Status
Last updated: 2026-02-28

---

## What Stride Is

An AI productivity coach delivered via SMS. Users set goals, check in daily,
and review progress weekly. The Scrum framework runs entirely under the hood —
users never see it. Plain language only.

**Interface:** SMS (Twilio A2P) → AWS Lambda → Strands AI agent → DynamoDB

---

## Phases

| Phase | Status | Description |
|---|---|---|
| **Sprint 0** | ✅ Done | Jupyter notebooks — proved Strands agent + tools + DynamoDB |
| **Sprint 1** | 🔄 In progress | Lambda stubs deployed, Terraform written, SMS wired |
| **Sprint 2** | ⏳ Not started | Real agent logic in handlers, opt-in flow, pattern learning |

---

## What Is Built and Verified

### Shared library (`scrumbot-app/shared/`)

#### `models.py` ✅
8 Pydantic v2 models covering every DynamoDB entity:

| Model | Key fields |
|---|---|
| `User` | user_id, name, email, created_at |
| `Project` | project_id, user_id, name, description, created_at |
| `WorkCycle` | cycle_id, project_id, name, goal, start_date, end_date, status |
| `Task` | task_id, cycle_id, title, description, estimate (pts), estimate_label, status |
| `Checkin` | checkin_id, user_id, date, did, doing, blocked, created_at |
| `Blocker` | blocker_id, task_id, description, resolved, created_at |
| `Velocity` | cycle_id, project_id, planned_points, delivered_points, cycle_name |
| `UserPattern` | user_id, avg_pace, avg_completion_rate, common_blockers, cycle_count |

All use `model_dump()` for DynamoDB writes. No ORM. No Pydantic v1 syntax.

---

#### `tools.py` ✅ — 10 tools total

All `@tool` decorated, all return `dict`, all catch exceptions.

| Tool | Purpose | DynamoDB operation |
|---|---|---|
| `create_project` | Create a new project for a user | PutItem `USER#{user_id}` / `PROJECT#{project_id}` |
| `create_work_cycle` | Create a work cycle under a project | PutItem `PROJECT#{project_id}` / `CYCLE#{cycle_id}` |
| `list_active_projects` | List all projects + their active cycle | Query `USER#{user_id}` begins_with `PROJECT#` |
| `create_task` | Add task to a cycle (S/M/L/XL estimate) | PutItem `CYCLE#{cycle_id}` / `TASK#{task_id}` |
| `update_task_status` | Move task to todo/in_progress/done/blocked | UpdateItem via GSI1 lookup |
| `get_cycle_data` | Get cycle + all its tasks | Query `CYCLE#{cycle_id}` begins_with `TASK#` |
| `create_checkin` | Record daily check-in (did/doing/blocked) | PutItem `USER#{user_id}` / `CHECKIN#{date}#{id}` |
| `flag_blocker` | Log a blocker against a task | PutItem `TASK#{task_id}` / `BLOCKER#{id}` |
| `get_pace_history` | Pace records + trend for a project | Query `PROJECT#{project_id}` begins_with `VELOCITY#` |
| `get_user_patterns` | Aggregated user habits | GetItem `USER#{user_id}` / `PATTERN#AGGREGATE` |

Estimate model: `S=2pts, M=5pts, L=8pts, XL=13pts (scope risk flag)`

---

#### `prompt.py` ✅
Single-source `STRIDE_SYSTEM_PROMPT`. Covers 5 session types, estimate rules,
scope boundary (non-negotiable — off-topic replies return exactly 2 sentences).

---

#### `db.py` ✅
- `get_table()` — boto3 Table factory, reads `DYNAMODB_TABLE_NAME` + `AWS_ENDPOINT_URL`
- `increment_rate_limit(user_id)` — atomic ADD counter `USER#{id}` / `RATELIMIT#{date}`, returns 0 on error (fail open)
- `log_blocked_attempt(user_id, reason, preview)` — writes `USER#{id}` / `BLOCKED#{timestamp}`, errors swallowed

---

#### `guards.py` ✅
- `check_message(message)` — returns `None` (pass), `"empty"`, or `"too_long"` (>500 chars)
- `check_rate_limit(user_id, limit=50)` — returns `True` if over daily limit (block)

---

### Lambda handlers (`scrumbot-app/functions/`)

| Handler | Route | Status | What it does |
|---|---|---|---|
| `checkin/handler.py` | `POST /checkin` | ⚠️ Stub | Returns `{"checkin_id": "stub", "message": "Check-in received"}` |
| `agent/handler.py` | `POST /ceremony` | ⚠️ Stub | Returns `{"reply": "stub", "history": []}` |
| `sms/handler.py` | `POST /sms` | ⚠️ Stub | Full guard chain works; returns stub reply after guards pass |

All three: Powertools `Logger` + `Tracer` + `APIGatewayHttpResolver`, both
decorators on `handler()`. No `print()`.

**`sms/handler.py` guard chain (fully implemented):**
1. Twilio signature validation (`RequestValidator`)
2. Message length/empty check (`check_message`)
3. Per-user rate limit — 50 msgs/day (`check_rate_limit`)
4. → Agent (currently stub, wired in Sprint 2)

---

### Local dev tools (`scrumbot-app/`)

| File | Purpose |
|---|---|
| `chat.py` | Interactive CLI — Strands Agent + all 10 tools, history preserved across turns |
| `local_server.py` | Flask HTTP server — `GET /health`, `POST /checkin`, `POST /ceremony` with guards |
| `.env` | Local config — LocalStack endpoint, dummy AWS creds, Anthropic key |

---

### Infrastructure (`scrumbot-infra/`) — Written, NOT deployed

| File | Status | What it creates |
|---|---|---|
| `bootstrap/main.tf` | ✅ Written | S3 `stride-tf-state` + DynamoDB `stride-tf-locks` (run once) |
| `versions.tf` | ✅ Written | Terraform ≥1.7, AWS provider ~>5.0, S3 backend config |
| `variables.tf` | ✅ Written | anthropic_api_key, twilio creds, environment, region, table name |
| `dynamodb.tf` | ✅ Written | `stride-prod` table — PAY_PER_REQUEST, pk/sk + GSI1 (gsi1pk/gsi1sk), PITR on |
| `iam.tf` | ✅ Written | Role `stride-lambda-exec` — BasicExecution + DynamoDB inline + X-Ray inline |
| `lambda.tf` | ✅ Written | 3 functions: `stride-checkin` (256MB/10s), `stride-agent` (512MB/30s), `stride-sms` (256MB/10s) |
| `api_gateway.tf` | ✅ Written | HTTP API `stride-api` — `POST /checkin`, `POST /ceremony`, `POST /sms` |
| `outputs.tf` | ✅ Written | api_gateway_url, function names, table name |
| `terraform.tfvars.example` | ✅ Written | Template — all vars, empty values, committed to git |
| `.github/workflows/terraform.yml` | ✅ Written | PR → fmt/validate/plan; main push → apply; OIDC auth |

**`terraform.tfvars` (not committed — contains secrets) has NOT been created yet.**
**`terraform apply` has NOT been run yet.**

---

### DynamoDB single-table design

**Table:** `stride-prod` (prod) / `stride-local` (local)
**Keys:** `pk` (String) / `sk` (String)
**GSI:** `gsi1` — `gsi1pk` / `gsi1sk`, projection ALL

| Entity | PK | SK | GSI1PK | GSI1SK |
|---|---|---|---|---|
| User | `USER#{user_id}` | `#METADATA` | — | — |
| Project | `USER#{user_id}` | `PROJECT#{project_id}` | `PROJECT#{project_id}` | `#METADATA` |
| Work cycle | `PROJECT#{project_id}` | `CYCLE#{cycle_id}` | `CYCLE#{cycle_id}` | `#METADATA` |
| Task | `CYCLE#{cycle_id}` | `TASK#{task_id}` | `TASK#{task_id}` | `STATUS#{status}` |
| Check-in | `USER#{user_id}` | `CHECKIN#{date}#{id}` | — | — |
| Blocker | `TASK#{task_id}` | `BLOCKER#{blocker_id}` | — | — |
| Velocity | `PROJECT#{project_id}` | `VELOCITY#{cycle_id}` | — | — |
| Pattern | `USER#{user_id}` | `PATTERN#AGGREGATE` | — | — |
| Rate limit | `USER#{user_id}` | `RATELIMIT#{YYYY-MM-DD}` | — | — |
| Blocked log | `USER#{user_id}` | `BLOCKED#{iso_timestamp}` | — | — |

---

### Legal / compliance (`docs/legal/`)

| File | Status |
|---|---|
| `privacy-policy.md` | ✅ Written — needs [YOUR EMAIL], [YOUR WEBSITE URL], [YOUR STATE] filled in |
| `terms-of-service.md` | ✅ Written — same placeholders |

Both cover SMS opt-in/out, data storage (AWS DynamoDB), Twilio + Anthropic as
processors, TCPA language, no data selling. Need to be published to a live URL
before Twilio A2P review can complete.

---

### Twilio / SMS

| Item | Status |
|---|---|
| A2P 10DLC Campaign registration | 🔄 In review (1–3 business days) |
| Toll-free number purchased | ❓ Confirm |
| Webhook URL set in Twilio console | ❌ Not yet — needs deploy first |
| Opt-in consent flow in code | ❌ Not implemented — Sprint 2 |

---

## What Is NOT Built Yet (Sprint 2)

### 1. Real agent logic in Lambda handlers — the big one

All three handlers return stubs. None of them call the Strands agent yet.

**`functions/agent/handler.py`** needs:
- Parse `user_id`, `type`, `message`, `history` from request body
- Cap history at 20 turns before passing to agent
- Instantiate `Agent(model=AnthropicModel(...), tools=[...all 10...], system_prompt=STRIDE_SYSTEM_PROMPT)`
- Run agent with message + history
- Return `{"reply": str, "history": updated_list}`

**`functions/checkin/handler.py`** needs:
- Parse `user_id`, `project_id`, `did`, `doing`, `blocked` from body
- Call `create_checkin` tool directly
- If `blocked` is non-empty, call `flag_blocker` for the relevant task
- Return real `checkin_id`

**`functions/sms/handler.py`** needs:
- After guards pass, look up or create user record
- Check opt-in consent status
- Route to agent with `type="checkin"` or detect session type from message
- Return real agent reply via TwiML

---

### 2. SMS opt-in consent flow (TCPA — legally required)

Before any SMS can be sent to beta users:

**New DynamoDB record needed:**

| Entity | PK | SK |
|---|---|---|
| Consent | `USER#{user_id}` | `CONSENT#PHONE` |

**Flow:**
1. User texts any message for the first time
2. Check for `CONSENT#PHONE` record — if missing, send opt-in prompt
3. `"Reply YES to receive Stride daily check-ins. Reply STOP anytime."`
4. If reply is "YES" → write `CONSENT#PHONE` with timestamp
5. All subsequent messages proceed normally
6. "STOP" → delete/flag consent record, send confirmation, stop all messages

This needs a new tool `check_consent(user_id)` and `record_consent(user_id, phone)`.

---

### 3. Velocity and pattern write-back

Currently `get_pace_history` and `get_user_patterns` can read data, but nothing
writes `Velocity` or `UserPattern` records after a cycle ends. These are needed
for the weekly review session to cite real numbers.

**Needs:**
- `record_velocity(project_id, cycle_id, planned_points, delivered_points)` — new tool
- `update_user_patterns(user_id, ...)` — new tool or inline logic after each review

---

### 4. Terraform deployment

Nothing is live yet. The full deploy sequence:

```bash
# 1. One-time bootstrap
cd scrumbot-infra/bootstrap
terraform init && terraform apply

# 2. Create terraform.tfvars (never commit)
cp scrumbot-infra/terraform.tfvars.example scrumbot-infra/terraform.tfvars
# Fill in: anthropic_api_key, twilio_auth_token, twilio_account_sid, twilio_phone_number

# 3. Deploy everything
cd scrumbot-infra
terraform init && terraform apply

# 4. Get webhook URL
terraform output api_gateway_url
# → paste into Twilio console as webhook for POST /sms
```

---

### 5. Smoke tests (post-deploy)

```bash
API=$(terraform -chdir=scrumbot-infra output -raw api_gateway_url)

# Check-in endpoint
curl -s -X POST $API/checkin \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","did":"built the tool layer","doing":"wiring the agent","blocked":""}' | jq .

# Agent endpoint
curl -s -X POST $API/ceremony \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","type":"setup","message":"I want to get set up","history":[]}' | jq .

# SMS: text your Twilio number and confirm reply in Messages app

# Tail logs
aws logs tail /aws/lambda/stride-checkin --follow
aws logs tail /aws/lambda/stride-agent --follow
aws logs tail /aws/lambda/stride-sms --follow
```

---

### 6. User record creation

There is a `User` model but no `create_user` tool and no onboarding flow that
creates the initial `USER#{user_id}` / `#METADATA` record. First-time SMS users
need to be bootstrapped into the system.

---

## Ordered Next Steps

| # | Task | Blocks | Effort |
|---|---|---|---|
| 1 | **Deploy Terraform** — create `terraform.tfvars`, bootstrap, apply | Smoke tests, Twilio webhook | 30 min |
| 2 | **Set Twilio webhook URL** — paste `api_gateway_url/sms` into Twilio console | Live SMS | 5 min |
| 3 | **Wire agent into `functions/agent/handler.py`** | Real ceremony responses | 2–3 hrs |
| 4 | **Wire agent into `functions/checkin/handler.py`** | Real check-in saves | 1 hr |
| 5 | **Build SMS opt-in consent flow** in `functions/sms/handler.py` | Legal SMS to beta users | 1–2 hrs |
| 6 | **Create user record on first SMS** — `USER#{id}` / `#METADATA` write | Patterns, history | 30 min |
| 7 | **Add `record_velocity` + `update_user_patterns` tools** | Weekly review with real numbers | 1–2 hrs |
| 8 | **Smoke test all 3 endpoints** | Confidence to invite beta users | 30 min |
| 9 | **Invite 10 beta users** | Dogfooding | — |
| 10 | **Publish Privacy Policy + Terms** to a live URL | A2P approval | 15 min |

---

## Definition of Done — Sprint 2

- [ ] All 3 Lambda handlers return real responses (no stubs)
- [ ] SMS opt-in consent flow enforced — no messages sent without YES reply
- [ ] First-time user creates `USER#` record automatically
- [ ] Weekly review cites real planned vs delivered numbers
- [ ] `terraform apply` exits 0 and all resources are live in us-east-1
- [ ] Smoke tests pass for all 3 endpoints
- [ ] CloudWatch shows structured JSON logs (no print output)
- [ ] X-Ray traces present for all 3 functions
- [ ] 10 beta users receiving and replying to real Stride messages
- [ ] Privacy Policy and Terms live at a public URL
- [ ] A2P Campaign fully approved

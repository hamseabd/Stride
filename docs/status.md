# Stride — Project Status
Last updated: 2026-03-01

---

## What Stride Is

An AI productivity coach delivered via SMS. Users set goals, check in daily,
and review progress weekly. The Scrum framework runs entirely under the hood —
users never see it. Plain language only.

**Interface:** SMS (Twilio A2P 10DLC) → AWS Lambda → Strands AI agent → DynamoDB

---

## Phases

| Phase | Status | Description |
|---|---|---|
| **Sprint 0** | ✅ Done | Jupyter notebooks — proved Strands agent + tools + DynamoDB |
| **Sprint 1** | ✅ Done | Renamed to Stride, Terraform written, Lambda stubs, SMS migration |
| **Sprint 2** | ✅ Code done | Real handlers, consent flow, onboarding — all locally tested and passing |
| **Sprint 3** | ⏳ Not started | Auth, Secrets Manager, proactive outbound SMS, pattern auto-update |

**Current state:** Initial git commit made (f6a31fb). Code is ready to push and deploy.
**Next action: push to GitHub → bootstrap Terraform → `terraform apply`**

---

## What Is Built and Verified (all locally tested ✅)

### Shared library (`scrumbot-app/shared/`)

#### `models.py` ✅
8 Pydantic v2 models covering every DynamoDB entity:

| Model | Key fields |
|---|---|
| `User` | user_id, name, email, **phone**, **onboarded**, created_at |
| `Project` | project_id, user_id, name, description, created_at |
| `WorkCycle` | cycle_id, project_id, name, goal, start_date, end_date, status |
| `Task` | task_id, cycle_id, title, description, estimate (pts), estimate_label, status |
| `Checkin` | checkin_id, user_id, date, did, doing, blocked, created_at |
| `Blocker` | blocker_id, task_id, description, resolved, created_at |
| `Velocity` | cycle_id, project_id, planned_points, delivered_points, cycle_name |
| `UserPattern` | user_id, avg_pace, avg_completion_rate, common_blockers, cycle_count |

`User.phone` and `User.onboarded` added in Sprint 2. All use `model_dump()` for DynamoDB writes.

---

#### `tools.py` ✅ — 13 tools total

All `@tool` decorated, all return `dict`, all catch exceptions.

| Tool | Purpose |
|---|---|
| `create_project` | Create a new project for a user |
| `create_work_cycle` | Create a new work cycle (week) under a project |
| `list_active_projects` | List all projects + their active cycle |
| `create_task` | Add a task to a work cycle (S/M/L/XL estimate) |
| `update_task_status` | Move a task to todo / in_progress / done / blocked |
| `get_cycle_data` | Get a work cycle + all its tasks |
| `create_checkin` | Record a daily check-in (did / doing / blocked) |
| `flag_blocker` | Log a blocker against a specific task |
| `get_pace_history` | Retrieve pace records for a project + compute trend |
| `get_user_patterns` | Retrieve aggregated patterns for a user |
| `record_velocity` | Write pace result after a cycle ends (planned vs delivered) |
| `update_user_patterns` | Update rolling averages after a weekly review |
| `complete_onboarding` | Mark a user as onboarded after first project + cycle + task created |

**Critical:** `avg_pace` and `avg_completion_rate` are written as `Decimal(str(value))` — Python `float` raises `TypeError` in boto3.

---

#### `db.py` ✅

**Connection:**
- `get_table()` — boto3 Table factory, reads `DYNAMODB_TABLE_NAME` + `AWS_ENDPOINT_URL`

**Rate limiting + blocked log:**
- `increment_rate_limit(user_id)` — atomic ADD counter, returns 0 on error (fail open)
- `log_blocked_attempt(user_id, reason, preview)` — writes `BLOCKED#{timestamp}`, errors swallowed

**SMS consent:**
- `get_consent(user_id)` — returns `CONSENT#SMS` item or None (fail open)
- `record_consent(user_id, phone)` — writes active consent, returns bool
- `revoke_consent(user_id)` — sets status=revoked, returns bool

**User bootstrap:**
- `get_or_create_user(user_id, phone)` — race-safe: conditional PutItem, catches `ConditionalCheckFailedException`
- `set_onboarded(user_id)` — sets `onboarded=True` on `USER#METADATA`, returns bool

---

#### `guards.py` ✅
- `check_message(message)` — returns `None` (pass), `"empty"`, or `"too_long"` (>500 chars)
- `check_rate_limit(user_id, limit=50)` — returns `True` if over daily limit (block)

---

#### `prompt.py` ✅
Single-source `STRIDE_SYSTEM_PROMPT`. Covers all 5 session types, estimate rules,
plain language rules. Imported by both Lambda handlers.

---

### Lambda handlers (`scrumbot-app/functions/`)

| Handler | Route | Status | What it does |
|---|---|---|---|
| `checkin/handler.py` | `POST /checkin` | ✅ Real | Direct tool calls — `create_checkin`, auto-flags blocker if `blocked` field non-empty |
| `agent/handler.py` | `POST /ceremony` | ✅ Real | Strands agent, 20-turn history cap, returns `{reply, history}` |
| `sms/handler.py` | `POST /sms` | ✅ Real | Full 10-step guard chain + consent flow + onboarding detection |

**SMS handler 10-step guard chain (fully implemented):**
1. Twilio signature validation → 403 if invalid
2. Parse `From` (user_id) + `Body`
3. `check_message()` → block if empty or >500 chars
4. `check_rate_limit()` → block if >50 msgs/day
5. STOP keyword → `revoke_consent()`, unsubscribe reply
6. HELP keyword → help text, no agent
7. `get_consent()` → no consent: send opt-in prompt; YES reply: `record_consent()` + welcome
8. `get_or_create_user()` → bootstrap `USER#` record
9. Onboarding check → inject setup instructions if `user.onboarded=False`
10. Agent call → `_call_agent()`, truncate reply at 1600 chars at sentence boundary

All errors return generic TwiML — stack traces never exposed via SMS.

---

### Infrastructure (`scrumbot-infra/`) — Written, NOT deployed

| File | Status | What it creates |
|---|---|---|
| `bootstrap/main.tf` | ✅ Written | S3 `stride-tf-state` + DynamoDB `stride-tf-locks` (run once) |
| `versions.tf` | ✅ Written | Terraform ≥1.7, AWS provider ~>5.0, S3 backend |
| `variables.tf` | ✅ Written | anthropic_api_key, twilio creds x3, environment, region, table name |
| `dynamodb.tf` | ✅ Written | `stride-prod` — PAY_PER_REQUEST, pk/sk + GSI1 (gsi1pk/gsi1sk), PITR on |
| `iam.tf` | ✅ Written | Role `stride-lambda-exec` — BasicExecution + DynamoDB inline + X-Ray inline |
| `lambda.tf` | ✅ Written | `stride-checkin` (256MB/10s), `stride-agent` (512MB/30s), `stride-sms` (256MB/10s) |
| `api_gateway.tf` | ✅ Written | HTTP API `stride-api` — `POST /checkin`, `POST /ceremony`, `POST /sms` |
| `outputs.tf` | ✅ Written | api_gateway_url, function names, table name |
| `terraform.tfvars.example` | ✅ Written | Template committed; actual `terraform.tfvars` is gitignored |
| `.github/workflows/terraform.yml` | ✅ Written | PR → fmt/validate/plan; main push → apply; OIDC auth |

`terraform.tfvars` (contains secrets) has **not been created yet**.
`terraform apply` has **not been run yet**.

---

### DynamoDB single-table design

**Table:** `stride-prod` (prod) / `stride-local` (local)
**Keys:** `pk` (String) / `sk` (String)
**GSI:** `gsi1` — `gsi1pk` / `gsi1sk`, projection ALL

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
| SMS Consent | `USER#{user_id}` | `CONSENT#SMS` |
| Rate limit | `USER#{user_id}` | `RATELIMIT#{YYYY-MM-DD}` |
| Blocked log | `USER#{user_id}` | `BLOCKED#{iso_timestamp}` |

---

### Git / repo

| Item | Status |
|---|---|
| Initial commit | ✅ Made (f6a31fb) — 32 files, 3280 insertions |
| Pushed to GitHub | ❌ Not yet — push with `git push -u origin main` |
| `.env` / `terraform.tfvars` committed | ✅ Correctly gitignored |
| `plan.md` | ✅ Gitignored (local planning file) |
| Local dev files (`chat.py`, `local_server.py`, `requirement-dev.txt`) | ✅ Gitignored |

---

### Legal / compliance (`docs/legal/`)

| File | Status |
|---|---|
| `privacy-policy.md` | ✅ Written — needs `[YOUR EMAIL]`, `[YOUR WEBSITE URL]`, `[YOUR STATE]` filled in |
| `terms-of-service.md` | ✅ Written — same placeholders |

Both cover SMS opt-in/out, DynamoDB storage, Twilio + Anthropic as processors, TCPA language.
Must be published to a live URL before Twilio A2P review can complete.

---

### Twilio / SMS

| Item | Status |
|---|---|
| A2P 10DLC Campaign registration | 🔄 In review (1–3 business days) |
| A2P 10DLC phone number | ❓ Confirm purchased |
| Webhook URL set in Twilio console | ❌ Not yet — needs deploy first |
| Opt-in consent flow in code | ✅ Implemented in `sms/handler.py` |

---

## Ordered Next Steps

| # | Task | Effort |
|---|---|---|
| 1 | **Push to GitHub** — `git push -u origin main` | 2 min |
| 2 | **Bootstrap Terraform state** — `cd scrumbot-infra/bootstrap && terraform init && terraform apply` | 5 min |
| 3 | **Create `terraform.tfvars`** — copy from example, fill in 4 secrets | 5 min |
| 4 | **Deploy** — `cd scrumbot-infra && terraform init && terraform apply` | 10 min |
| 5 | **Set Twilio webhook** — paste `{api_gateway_url}/sms` into Twilio Console | 2 min |
| 6 | **Smoke test** all 3 endpoints + real SMS round-trip | 15 min |
| 7 | **Publish Privacy Policy + Terms** to live URL (Notion or GitHub Pages) | 15 min |
| 8 | **Invite 10 beta users** after A2P approval + smoke tests pass | — |

---

## Smoke test commands (post-deploy)

```bash
API=$(terraform -chdir=scrumbot-infra output -raw api_gateway_url)

# Check-in
curl -s -X POST $API/checkin \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","project_id":"p1","did":"wrote code","doing":"testing","blocked":""}' | jq .

# Agent
curl -s -X POST $API/ceremony \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","type":"setup","message":"I want to get started","history":[]}' | jq .

# SMS: text your Twilio number, confirm reply in Messages app

# Tail logs
aws logs tail /aws/lambda/stride-checkin --follow
aws logs tail /aws/lambda/stride-agent --follow
aws logs tail /aws/lambda/stride-sms --follow
```

---

## Definition of Done — Sprint 2 (pending deploy)

- [x] All 3 Lambda handlers return real responses (no stubs)
- [x] SMS opt-in consent flow enforced — no messages sent without YES reply
- [x] First-time user creates `USER#` record automatically (`get_or_create_user`)
- [x] Weekly review tools write real velocity + pattern data
- [x] 13 tools in `shared/tools.py` — plain language names, no Scrum jargon
- [ ] `terraform apply` exits 0 — all resources live in us-east-1
- [ ] Smoke tests pass for all 3 endpoints
- [ ] CloudWatch shows structured JSON logs (no print output)
- [ ] X-Ray traces present for all 3 functions
- [ ] Real SMS round-trip with opt-in flow works end-to-end
- [ ] Privacy Policy + Terms live at a public URL
- [ ] A2P Campaign fully approved
- [ ] 10 beta users onboarded

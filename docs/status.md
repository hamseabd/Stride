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
| **Sprint 2** | ✅ Done | Real handlers, consent flow, onboarding, all 3 endpoints live |
| **Sprint 3** | ⏳ Not started | Auth, Secrets Manager, proactive outbound SMS, pattern auto-update |

**Current state:** Deployed. All 3 endpoints live at `https://cbkpntvax6.execute-api.us-east-1.amazonaws.com`

---

## Infrastructure — Live in us-east-1

| Resource | Name | Status |
|---|---|---|
| API Gateway (HTTP) | `stride-api` | ✅ Live |
| Lambda | `stride-checkin` | ✅ Live (256MB / 10s / ARM64) |
| Lambda | `stride-agent` | ✅ Live (512MB / 30s / ARM64) |
| Lambda | `stride-sms` | ✅ Live (256MB / 15s / ARM64) |
| DynamoDB | `stride-prod` | ✅ Live (PAY_PER_REQUEST, PITR on) |
| ECR | `stride-checkin/agent/sms` | ✅ Live (lifecycle: keep last 10 sha- tags) |
| IAM Role | `stride-lambda-exec` | ✅ Live |
| S3 | `stride-tf-state` | ✅ Live (Terraform remote state) |
| DynamoDB | `stride-tf-locks` | ✅ Live (Terraform state lock) |

**Deployment method:** Lambda container images (Linux ARM64 / `public.ecr.aws/lambda/python:3.12`)
**Terraform state:** Remote — S3 + DynamoDB lock

---

## Endpoints

| Route | Lambda | Purpose |
|---|---|---|
| `POST /checkin` | `stride-checkin` | Daily check-in — direct tool calls, no agent |
| `POST /ceremony` | `stride-agent` | All conversational flows — Strands agent |
| `POST /sms` | `stride-sms` | Twilio webhook — full guard chain + consent |

---

## Shared library (`scrumbot-app/shared/`)

### `models.py` ✅
8 Pydantic v2 models covering every DynamoDB entity:

| Model | Key fields |
|---|---|
| `User` | user_id, name, email, phone, onboarded, created_at |
| `Project` | project_id, user_id, name, description, created_at |
| `WorkCycle` | cycle_id, project_id, name, goal, start_date, end_date, status |
| `Task` | task_id, cycle_id, title, description, estimate (pts), estimate_label, status |
| `Checkin` | checkin_id, user_id, date, did, doing, blocked, created_at |
| `Blocker` | blocker_id, task_id, description, resolved, created_at |
| `Velocity` | cycle_id, project_id, planned_points, delivered_points, cycle_name |
| `UserPattern` | user_id, avg_pace, avg_completion_rate, common_blockers, cycle_count |

### `tools.py` ✅ — 13 tools

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

### `db.py` ✅
- `get_table()` — boto3 Table factory
- `increment_rate_limit(user_id)` — atomic ADD counter, fail open
- `log_blocked_attempt(user_id, reason, preview)` — writes `BLOCKED#{timestamp}`
- `get_consent / record_consent / revoke_consent` — TCPA SMS consent
- `get_or_create_user(user_id, phone)` — race-safe conditional PutItem
- `set_onboarded(user_id)` — sets `onboarded=True`

### `guards.py` ✅
- `check_message(message)` — `None` (pass), `"empty"`, or `"too_long"` (>500 chars)
- `check_rate_limit(user_id, limit=50)` — `True` if over daily limit

### `prompt.py` ✅
Single-source `STRIDE_SYSTEM_PROMPT`. Covers all 5 session types, estimate rules, plain language rules.

---

## Lambda handlers (`scrumbot-app/functions/`)

### `checkin/handler.py` — `POST /checkin` ✅
Direct tool calls: `create_checkin`, optional `flag_blocker` if blocked field non-empty.

### `agent/handler.py` — `POST /ceremony` ✅
Strands agent with all 13 tools. 20-turn history cap. Returns `{reply, history}`.

### `sms/handler.py` — `POST /sms` ✅
10-step guard chain:
1. Twilio signature validation → 403 if invalid
2. Parse `From` (user_id) + `Body`
3. `check_message()` → block if empty or >500 chars
4. `check_rate_limit()` → block if >50 msgs/day
5. STOP keyword → revoke consent, unsubscribe reply
6. HELP keyword → help text, no agent
7. `get_consent()` → no consent: send opt-in prompt; YES reply: record consent + welcome
8. `get_or_create_user()` → bootstrap `USER#` record
9. Onboarding check → inject setup instructions if `user.onboarded=False`
10. Agent call → `_call_agent()`, truncate at 1600 chars at sentence boundary

---

## DynamoDB single-table design

**Table:** `stride-prod` (prod) / `stride-local` (local dev)
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

## Git / repo

| Item | Status |
|---|---|
| Repository | ✅ `github.com/hamseabd/Stride` |
| Latest commit | ✅ `0532304` — container image migration |
| `.env` / `terraform.tfvars` | ✅ Gitignored (secrets never committed) |
| `plan.md` | ✅ Gitignored (local planning file) |
| Local dev files (`chat.py`, `local_server.py`, `requirement-dev.txt`) | ✅ Gitignored |

---

## Legal / compliance (`docs/legal/`)

| File | Status |
|---|---|
| `privacy-policy.md` | ✅ Written — needs `[YOUR EMAIL]` and `[YOUR WEBSITE URL]` filled in |
| `terms-of-service.md` | ✅ Written — needs name, email, website, state/country filled in |

Both cover SMS opt-in/out, DynamoDB storage, Twilio + Anthropic as processors, TCPA language.
Must be published to a live URL before Twilio A2P review can complete.

---

## Twilio / SMS

| Item | Status |
|---|---|
| Phone number | ✅ `+14049485133` (10DLC, Atlanta GA) |
| Webhook URL set in Twilio console | ⏳ Pending — set to `{api_gateway_url}/sms` |
| A2P 10DLC Campaign registration | 🔄 In review (1–3 business days) |
| Opt-in consent flow | ✅ Implemented in `sms/handler.py` |
| Real SMS round-trip tested | ⏳ Pending webhook config |

---

## Next Steps

| # | Task | Effort |
|---|---|---|
| 1 | **Set Twilio webhook** — paste `https://cbkpntvax6.execute-api.us-east-1.amazonaws.com/sms` into Twilio Console | 2 min |
| 2 | **Real SMS smoke test** — text the number, confirm opt-in flow + agent reply | 15 min |
| 3 | **Fill legal placeholders** — email, website URL, state in `docs/legal/` | 10 min |
| 4 | **Publish legal docs** — GitHub Pages or Notion public page | 15 min |
| 5 | **A2P approval** — wait for Twilio campaign approval (1–3 days) | — |
| 6 | **Invite beta users** — once A2P approved + smoke tests pass | — |

---

## Quick reference

```bash
# Live API
API="https://cbkpntvax6.execute-api.us-east-1.amazonaws.com"

# Check-in
curl -s -X POST $API/checkin \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hamse","did":"built something","doing":"testing","blocked":""}' | python3 -m json.tool

# Ceremony
curl -s -X POST $API/ceremony \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hamse","type":"setup","message":"I want to get set up","history":[]}' | python3 -m json.tool

# Logs
aws logs tail /aws/lambda/stride-checkin --follow
aws logs tail /aws/lambda/stride-agent --follow
aws logs tail /aws/lambda/stride-sms --follow

# Redeploy
make deploy                        # build + push + terraform apply
make push                          # build + push only (no infra change)
make up                            # local dev with LocalStack
```

---

## Definition of Done — Sprint 2

- [x] All 3 Lambda handlers return real responses (no stubs)
- [x] SMS opt-in consent flow enforced — no messages sent without YES reply
- [x] First-time user creates `USER#` record automatically
- [x] Weekly review tools write real velocity + pattern data
- [x] 13 tools in `shared/tools.py` — plain language names, no Scrum jargon
- [x] `terraform apply` exits 0 — all resources live in us-east-1
- [x] Smoke tests pass for `/checkin` and `/ceremony`
- [x] CloudWatch shows structured JSON logs
- [x] X-Ray traces present for all 3 functions
- [ ] Real SMS round-trip with opt-in flow works end-to-end
- [ ] Privacy Policy + Terms live at a public URL
- [ ] A2P Campaign fully approved
- [ ] Beta users onboarded

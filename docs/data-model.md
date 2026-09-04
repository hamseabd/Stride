# Data model

Stride stores all application state in a single DynamoDB table with pay-per-request billing. A single table design reduces operational complexity, enables atomic multi-item operations, and caps costs at the usage level without provisioned capacity.

## One table

**Table name:** `stride-prod` in production, `stride-local` in local development. Always read from the environment variable `DYNAMODB_TABLE_NAME`.

**Billing:** PAY_PER_REQUEST (on-demand). No provisioned capacity. Cost scales with actual read and write volume.

**Attributes:**
- `pk` (String, Partition key): Entity family + identifier (e.g., `USER#+1234567890`)
- `sk` (String, Sort key): Entity type + sub-id (e.g., `PROJECT#proj-123`)
- `gsi1pk` (String): Global secondary index 1 partition key. Used for reverse lookups and cross-entity queries (e.g., list all projects matching `PROJECT#proj-123`)
- `gsi1sk` (String): Global secondary index 1 sort key. Pairs with `gsi1pk` for multi-entity queries

**GSI1 projection:** ALL attributes. No sparse projection; every item is indexed on GSI1.

[ADR-0005](adr/0005-single-table-dynamodb.md) documents why a single table is the only acceptable design for Stride.

## Key patterns

| Entity | PK | SK | GSI1PK | GSI1SK |
|---|---|---|---|---|
| User | `USER#{user_id}` | `#METADATA` | — | — |
| Project | `USER#{user_id}` | `PROJECT#{project_id}` | `PROJECT#{project_id}` | `#METADATA` |
| Work cycle | `PROJECT#{project_id}` | `CYCLE#{cycle_id}` | `CYCLE#{cycle_id}` | `#METADATA` |
| Task | `CYCLE#{cycle_id}` | `TASK#{task_id}` | `TASK#{task_id}` | `STATUS#{status}` |
| Check-in | `USER#{user_id}` | `CHECKIN#{YYYY-MM-DD}#{checkin_id}` | — | — |
| Blocker | `TASK#{task_id}` | `BLOCKER#{blocker_id}` | — | — |
| Velocity | `PROJECT#{project_id}` | `VELOCITY#{cycle_id}` | — | — |
| Pattern (agg) | `USER#{user_id}` | `PATTERN#AGGREGATE` | — | — |
| SMS Consent | `USER#{user_id}` | `CONSENT#SMS` | — | — |
| Rate limit | `USER#{user_id}` | `RATELIMIT#{YYYY-MM-DD}` | — | — |
| Blocked log | `USER#{user_id}` | `BLOCKED#{iso_timestamp}` | — | — |
| Conversation | `USER#{user_id}` | `CONVERSATION#CURRENT` | — | — |
| Feedback | `USER#{user_id}` | `FEEDBACK#{iso_timestamp}` | — | — |
| Proactive consent | `USER#{user_id}` | `CONSENT#PROACTIVE` | `PROACTIVE#ACTIVE` | `USER#{user_id}` |
| Outbound message | `USER#{user_id}` | `OUTBOUND#{iso_timestamp}` | — | — |
| Habit | `USER#{user_id}` | `HABIT#{habit_id}` | — | — |

## Access patterns

| Pattern | Query | Key |
|---|---|---|
| Get user metadata | get_item | PK: `USER#{user_id}`, SK: `#METADATA` |
| List user projects | query | PK: `USER#{user_id}`, SK begins_with `PROJECT#` |
| Get project | query | GSI1PK: `PROJECT#{project_id}`, SK: `#METADATA` |
| List project cycles | query | PK: `PROJECT#{project_id}`, SK begins_with `CYCLE#` |
| Get cycle | query | GSI1PK: `CYCLE#{cycle_id}`, SK: `#METADATA` |
| List cycle tasks | query | PK: `CYCLE#{cycle_id}`, SK begins_with `TASK#` |
| Get task | query | GSI1PK: `TASK#{task_id}` |
| List user check-ins | query | PK: `USER#{user_id}`, SK begins_with `CHECKIN#` |
| List task blockers | query | PK: `TASK#{task_id}`, SK begins_with `BLOCKER#` |
| Pace history | query | PK: `PROJECT#{project_id}`, SK begins_with `VELOCITY#` |
| User patterns | get_item | PK: `USER#{user_id}`, SK: `PATTERN#AGGREGATE` |
| SMS consent | get_item | PK: `USER#{user_id}`, SK: `CONSENT#SMS` |
| Rate limit counter | get_item | PK: `USER#{user_id}`, SK: `RATELIMIT#{YYYY-MM-DD}` |
| Consented users (proactive) | query | GSI1PK: `PROACTIVE#ACTIVE` |

## Record types

**User** (`USER#{user_id}/#METADATA`): Account metadata. Fields: `phone`, `name`, `onboarded`, `timezone`, `planning_day`, `checkin_time`, `evening_time`, `preferred_tone`, `created_at`.

**SMS Consent** (`USER#{user_id}/CONSENT#SMS`): Tracks opt-in/opt-out status for SMS messaging. Fields: `status` (active / revoked), `created_at`, `revoked_at`.

**Proactive consent** (`USER#{user_id}/CONSENT#PROACTIVE`): Separate opt-in for outbound nudges. Used by the scheduler to query all users who have consented to proactive messages. Fields: `status` (active / revoked), `gsi1pk` = `PROACTIVE#ACTIVE`, `gsi1sk` = `USER#{user_id}`, `created_at`, `revoked_at`.

**Outbound message** (`USER#{user_id}/OUTBOUND#{iso_timestamp}`): Log of proactive messages sent by the scheduler. Fields: `message_type` (morning_reminder / evening_checkin / monday_planning / friday_review / midweek_adjust), `body`, `sent_at`, `replied_at` (null until the user replies within 6 hours).

**Conversation** (`USER#{user_id}/CONVERSATION#CURRENT`): Current message history, capped at 20 turns. Stored as a list of message dicts (from both user and agent). Refreshed on every user message.

**Blocked attempt** (`USER#{user_id}/BLOCKED#{iso_timestamp}`): Log of rejected inbound messages. Fields: `reason` (empty / too_long / rate_limit), `message_preview` (first 100 chars), `logged_at`.

**Feedback** (`USER#{user_id}/FEEDBACK#{iso_timestamp}`): User feedback collected by `submit_feedback` tool. Fields: `text`, `source` (user-initiated / agent-prompted), `created_at`.

## Rules

**Decimal for floats:** All float values written to DynamoDB must be `Decimal` type. This includes `avg_pace`, `avg_completion_rate` in patterns, and any derived metrics. Use `Decimal(str(value))` before writing. Python's native `float` raises `TypeError` at DynamoDB write time.

**Conversation history cap:** The `CONVERSATION#CURRENT` record stores at most 20 turns (message pairs). When a new message arrives, the oldest turns are dropped before saving. This prevents unbounded context growth and keeps agent latency predictable.

**No scans:** All queries must use `get_item` (single item) or `query` (using PK or GSI1). Never `scan` in Lambda handlers. The scheduler queries consented users via `query` on GSI1PK = `PROACTIVE#ACTIVE` — this is the single exception where GSI is essential to avoid a table scan.

**Blocked log:** Rejected messages are logged to `BLOCKED#{iso_timestamp}` with a reason (empty, too_long, rate_limit). This aids debugging and abuse monitoring without storing the full message text (PII concern).

**Outbound tracking:** The scheduler writes `OUTBOUND#{iso_timestamp}` records for every proactive message sent. When the user replies within 6 hours, the inbound SMS handler sets `replied_at` on the matching outbound record, enabling session-aware context injection (see `_build_user_context` in the SMS handler).

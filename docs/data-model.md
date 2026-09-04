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

| Pattern | PK | SK / Condition |
|---|---|---|
| List user projects | `USER#{user_id}` | begins_with `PROJECT#` |
| Get project by ID | GSI1: `PROJECT#{project_id}` | `#METADATA` |
| List project cycles | `PROJECT#{project_id}` | begins_with `CYCLE#` |
| Get cycle by ID | GSI1: `CYCLE#{cycle_id}` | `#METADATA` |
| List cycle tasks | `CYCLE#{cycle_id}` | begins_with `TASK#` |
| Get task by ID | GSI1: `TASK#{task_id}` | (any) |
| User check-ins | `USER#{user_id}` | begins_with `CHECKIN#` |
| Task blockers | `TASK#{task_id}` | begins_with `BLOCKER#` |
| Pace history | `PROJECT#{project_id}` | begins_with `VELOCITY#` |
| User patterns | `USER#{user_id}` | `PATTERN#AGGREGATE` |
| SMS consent | `USER#{user_id}` | `CONSENT#SMS` |
| Rate limit counter | `USER#{user_id}` | `RATELIMIT#{YYYY-MM-DD}` |

## Record types

- **User** (`USER#{user_id}/#METADATA`): Account metadata — phone, name, onboarded, timezone, planning_day, checkin_time, evening_time, preferred_tone.
- **SMS Consent** (`USER#{user_id}/CONSENT#SMS`): Opt-in/opt-out status for SMS messaging.
- **Proactive consent** (`USER#{user_id}/CONSENT#PROACTIVE`): Separate opt-in for outbound messages; indexed by `PROACTIVE#ACTIVE` GSI for scheduler lookup.
- **Outbound message** (`USER#{user_id}/OUTBOUND#{iso_timestamp}`): Log of proactive nudges sent, with optional `replied_at` timestamp if user replied within 6 hours.
- **Conversation** (`USER#{user_id}/CONVERSATION#CURRENT`): Current message history, capped at 20 turns.
- **Blocked attempt** (`USER#{user_id}/BLOCKED#{iso_timestamp}`): Rejected inbound message with reason (empty, too_long, rate_limit).
- **Feedback** (`USER#{user_id}/FEEDBACK#{iso_timestamp}`): User feedback from `submit_feedback` tool.

## Rules

**Decimal for floats:** Float fields (`avg_pace`, `avg_completion_rate`) must be `Decimal` type before writing to DynamoDB. Python's native `float` raises `TypeError`.

**Conversation cap:** At most 20 turns per `CONVERSATION#CURRENT`. Oldest turns are dropped on new messages.

**No scans:** All queries use `get_item` or `query`. Scheduler queries consented users via GSI1PK = `PROACTIVE#ACTIVE` — the only exception to avoid table scan.

**Blocked log:** `BLOCKED#{iso_timestamp}` records rejected messages with reason. Aids debugging without storing full text (PII).

**Outbound tracking:** `OUTBOUND#{iso_timestamp}` records include `replied_at` if user replies within 6 hours, enabling session-aware context injection.

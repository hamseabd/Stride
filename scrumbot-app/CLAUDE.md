# CLAUDE.md — scrumbot-app

## What this repo is
Python application code for **Stride** — a personal productivity coach for anyone with goals.
This repo contains: shared library (`shared/`), Lambda handlers (`functions/`).

Sprint 0 notebooks have been deleted. Sprint 1 and Sprint 2 code are complete.
**Current state: all code locally tested and passing. Next step is AWS deployment.**

## What this repo is NOT
- No Terraform. No infrastructure code. Infrastructure lives in `scrumbot-infra/`.
- No UI. No frontend. No HTML. API-first only.
- No raw Anthropic SDK calls. All agent logic uses Strands SDK.

---

## Stack
- **Python 3.12** — no f-strings or syntax from 3.13+
- **Strands SDK** (`strands-agents==0.1.6`) — all agent and tool logic
- **Claude `claude-sonnet-4-6`** via Anthropic API — never Bedrock, never OpenAI
- **boto3** — DynamoDB only. No other AWS services without explicit instruction.
- **AWS Lambda Powertools v3** — logging, tracing, metrics on every Lambda handler
- **Pydantic v2** — data models in `shared/models.py`
- **LocalStack** — local DynamoDB endpoint for development
- **twilio** — SMS webhook validation + TwiML responses (`stride-sms` function)

---

## Directory layout

```
scrumbot-app/
├── functions/
│   ├── checkin/
│   │   ├── __init__.py
│   │   └── handler.py      # POST /checkin — direct tool calls, no agent
│   ├── agent/
│   │   ├── __init__.py
│   │   └── handler.py      # POST /ceremony — Strands agent, all 13 tools
│   └── sms/
│       ├── __init__.py
│       └── handler.py      # POST /sms — Twilio webhook, full guard + consent + agent
├── shared/
│   ├── __init__.py
│   ├── tools.py            # ALL Strands @tool definitions (13 tools) — never inline
│   ├── db.py               # boto3 client + consent + user bootstrap functions
│   ├── models.py           # Pydantic v2 models — one per DynamoDB entity
│   ├── prompt.py           # STRIDE_SYSTEM_PROMPT — single source of truth
│   └── guards.py           # check_message(), check_rate_limit()
└── tests/
```

**Local-only files (gitignored):**
- `chat.py` — interactive CLI for testing agent flows locally
- `local_server.py` — Flask server mirroring the production API
- `requirement-dev.txt` — dev dependencies (pytest, flask, aws-xray-sdk, etc.)

Never create files outside this structure without being told to.

---

## Environment variables

Always read from environment. Never hardcode. All must be present for local dev:

| Variable | Local value | Lambda value |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Env var on Lambda (Secrets Manager in Sprint 3) |
| `DYNAMODB_TABLE_NAME` | `stride-local` | `stride-prod` |
| `ENVIRONMENT` | `local` | `prod` |
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | Not set (omit from boto3 call) |
| `TWILIO_ACCOUNT_SID` | (optional locally) | Required on stride-sms |
| `TWILIO_AUTH_TOKEN` | (optional locally) | Required on stride-sms |
| `TWILIO_PHONE_NUMBER` | (optional locally) | Required on stride-sms (E.164, e.g. +18005551234) |

**`AWS_ENDPOINT_URL` handling:**
```python
import os
endpoint = os.getenv("AWS_ENDPOINT_URL")  # None in Lambda, set locally
kwargs = {"endpoint_url": endpoint} if endpoint else {}
boto3.resource("dynamodb", **kwargs)
```
This pattern is the only acceptable way to handle the local/Lambda endpoint difference.

---

## DynamoDB — single-table rules

**Table name:** always from `os.getenv("DYNAMODB_TABLE_NAME")`.
**One table. Always.** No exceptions. No new tables.

### PK / SK patterns

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

**GSI name:** `gsi1`
**GSI attributes:** `gsi1pk` (String), `gsi1sk` (String), projection ALL

Never use Scan. Every read must be a `get_item` or `query` using PK or GSI.

### Access patterns

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

---

## Stride tools (shared/tools.py)

**13 tools total.** All follow the same patterns (Powertools logger, try/except → return dict).

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

**Estimate model:**
- S → 2 points (a few hours)
- M → 5 points (a day or two)
- L → 8 points (most of the week)
- XL → 13 points (more than a week — flag as scope risk)

**Session types (POST /ceremony `type` field):**
- `setup` — first-time onboarding
- `planning` — plan your week
- `checkin` — daily check-in
- `review` — weekly review
- `refinement` — adjust your plan

**Critical:** `update_user_patterns` stores `avg_pace` and `avg_completion_rate` as
`Decimal` (not `float`) before writing to DynamoDB. Python `float` raises `TypeError`
at write time. Always use `Decimal(str(value))` for float fields going to DynamoDB.

---

## db.py functions

**Connection:**
- `get_table()` — returns boto3 Table resource, reads `DYNAMODB_TABLE_NAME` + `AWS_ENDPOINT_URL`

**Rate limiting + blocked log:**
- `increment_rate_limit(user_id)` — atomic ADD counter, returns new count, returns 0 on error (fail open)
- `log_blocked_attempt(user_id, reason, message_preview)` — writes BLOCKED# record, errors swallowed

**SMS consent:**
- `get_consent(user_id)` — returns CONSENT#SMS item or None (fail open)
- `record_consent(user_id, phone)` — writes active consent, returns bool
- `revoke_consent(user_id)` — sets status=revoked, returns bool

**User bootstrap:**
- `get_or_create_user(user_id, phone)` — get or create USER#METADATA record, race-safe
- `set_onboarded(user_id)` — sets onboarded=True on USER#METADATA, returns bool

---

## Strands tool conventions

All tools live in `shared/tools.py`. Never define a tool inline in a handler.

```python
from strands import tool
from aws_lambda_powertools import Logger

logger = Logger()

@tool
def my_tool(param: str) -> dict:
    """
    Docstring is sent to Claude as the tool description.
    Must describe: what the tool does, all params, return shape, error shape.
    Be precise. Claude reads this — not humans.
    """
    try:
        # implementation
        return {"result": "value"}
    except Exception as e:
        logger.exception("my_tool failed")
        return {"error": str(e)}
```

**Rules:**
- `@tool` decorator always present
- Return type is always `dict`
- Never raise from a tool — catch all exceptions, return `{"error": str(e)}`
- Docstring must specify: params, return keys, error key behaviour
- Logger from Powertools — no `print()`, no `logging.getLogger()`

---

## Lambda handler conventions

Every handler follows this exact pattern:

```python
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()

@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
```

No bare `logging`. No `print()`. No handler without both decorators.

**Agent instantiation pattern** (used in `functions/agent/handler.py` and `functions/sms/handler.py`):
```python
from strands import Agent
from strands.models.anthropic import AnthropicModel

model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
agent = Agent(model=model, system_prompt=system, tools=TOOLS, messages=history)
result = agent(message)
# agent.messages contains the updated history
```

---

## SMS handler flow (`functions/sms/handler.py`)

```
Inbound SMS
├── 1. Twilio signature validation    → 403 if invalid
├── 2. Parse From (user_id) + Body
├── 3. check_message()                → block if empty or >500 chars
├── 4. check_rate_limit()             → block if >50 msgs/day
├── 5. STOP keyword                   → revoke_consent(), unsubscribe reply
├── 6. HELP keyword                   → help text, no agent
├── 7. get_consent()
│   ├── No consent / revoked          → send opt-in prompt
│   └── YES keyword                   → record_consent(), welcome message
├── 8. get_or_create_user()           → bootstrap USER# record
├── 9. Onboarding check               → inject setup instructions if no projects
└── 10. Agent call                    → _call_agent(), truncate reply at 1600 chars
```

All errors return a generic TwiML reply — never expose stack traces via SMS.

---

## Models conventions

```python
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

def _uuid() -> str:
    return str(uuid.uuid4())

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

class MyModel(BaseModel):
    entity_id: str = Field(default_factory=_uuid)
    created_at: str = Field(default_factory=_now)
```

- Use `model.model_dump()` for DynamoDB writes
- No ORM, no database logic in models
- `User` model has `phone: str = ""` and `onboarded: bool = False`
- Float fields (`avg_pace`, `avg_completion_rate` in `UserPattern`) must be
  converted to `Decimal` before DynamoDB writes

---

## Error handling

| Context | Rule |
|---|---|
| Strands tools | Catch all, return `{"error": str(e)}` |
| Lambda handlers | Catch all, return `{"statusCode": 500, "body": json.dumps({"error": str(e)})}` |
| SMS handler errors | Catch all, return generic TwiML — never expose internals |
| db.py functions | Catch all, log error, return safe default (None / False / 0) |
| Models | Let Pydantic raise `ValidationError` — do not catch in models |

---

## Logging

```python
from aws_lambda_powertools import Logger
logger = Logger()

logger.info("Task created", task_id=task_id, cycle_id=cycle_id)
logger.error("Tool failed", error=str(e), tool="create_task")
```

Never: `print()`, `logging.basicConfig()`, `logging.getLogger()`.
Never log message content (PII). Always log user_id for traceability.

---

## Hard constraints — enforce always

1. No new AWS services. DynamoDB only.
2. No Scan operations on DynamoDB.
3. No raw Anthropic SDK. Strands only.
4. No hardcoded AWS credentials, endpoints, table names, or regions.
5. No `print()` anywhere. Powertools logger only.
6. No tool defined outside `shared/tools.py`.
7. No Pydantic v1 syntax. v2 only (`model_dump()` not `dict()`).
8. `AWS_ENDPOINT_URL` controls local vs Lambda — the conditional kwargs pattern is mandatory.
9. No "ScrumBot", "sprint" (user-facing), "story", "standup", or "Fibonacci" in any file.
10. Float fields written to DynamoDB must be `Decimal` — use `Decimal(str(value))`.
11. SMS opt-in consent required before any agent message is sent — TCPA compliance.
12. History cap: 20 turns max before passing to agent — no unbounded context growth.
13. SMS responses truncated at 1600 chars at a sentence boundary.

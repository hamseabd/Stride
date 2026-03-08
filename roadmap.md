# Stride — Product Evolution Roadmap

## Context

Stride is deployed and live (Sprint 2 complete). A2P 10DLC campaign in review (up to 3 weeks). This roadmap defines the full product evolution: individual beta → team version → payments.

**Timeline:** 3 weeks to build while waiting for Twilio approval. Beta starts when A2P is live.

---

## Decisions (All Locked In)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Beta scope | Individual only, 10 free users for ~1 month | Validate the core experience first. Focus on value, not monetization. |
| Team timing | After beta, not during | Research showed 6/13 tools + all 7 db.py functions need changes. Better to ship a great individual product than a half-baked team one. |
| Team identity | Second Twilio number (shared for all teams) | Industry standard: one number = one context. $1.15/mo. No in-band context switching. |
| Team/personal overlap | Pick one per phone number | If you're on a team, that number is team-only. Want personal? Use the individual Stride number separately. |
| Conversation memory | Reset Monday (planning day) after review data is stored | 20 turns lasts a full week. Agent still has all data via tools. Matches Stride's weekly rhythm. |
| Weekly rhythm | Spread across week: Fri=review, Mon=plan, Wed=adjust, daily=check-in | Different mindsets on different days. Friday reflects, Monday plans fresh. |
| Capacity language | Time-based, never expose points | "3 days of work" not "15 pts." Points run under the hood, users see time. |
| Prioritization | Capacity-aware, plain language | "That's 7 days of work for a 5-day week. What can wait?" |
| New projects | Anytime, shows up in next planning session | No friction. "Created Marketing Site! Plan it now or Monday?" |
| Goal model | Projects = Goals with target dates + milestones | User says "launch portfolio in 3 months" → Stride breaks into milestones → weekly tasks. Existing WorkCycle = milestone. |
| Habits | Separate from goals, recurring, streak-tracked | "Write 30 min daily" or "Exercise 3x/week." Shows in morning messages alongside goal tasks. |
| Multiple goals | Yes, Stride helps balance with capacity language | "You've got 3 goals and 3 days of work. Portfolio needs 2 days, Blog needs 1." |
| Goal decomposition | Stride leads, user confirms/adjusts | Stride suggests milestones and weekly tasks. User can override. Monday planning references the big goal + current milestone. |
| Proactive messaging | Build during the 3-week wait, ships with beta | It's the #1 differentiator. A to-do app waits. Stride texts first. |
| Free tier | All features during beta | Decide what to gate after seeing what users actually value. |
| Payments | After beta (Stripe Payment Links via SMS) | No web page needed. $12/mo individual, $12/seat/mo team. |
| Admin summaries | Agent-generated (not templates) | ~$3/mo for 10 teams. Stride's coaching voice stays consistent. |
| Data moat fields | Add 3 fields to existing models NOW | status_changed_at, blocker category, active_project_count. Captures pattern data from day one of beta. |
| Local dev tooling | Build chat.py CLI + /test-scheduler endpoint | Interactive SMS simulator + manual scheduler trigger. ~1 day, huge Sprint 3 productivity boost. |
| Pricing model | Decide after beta | Beta is free. See what features users value, then design pricing around data. |
| Phase 0 fixes | Fix existing tools before new features | create_project needs target_date, list_active_projects doesn't return it, no update_project tool, no set_user_preference tool, max_tokens too low. |
| Timezone-aware dates | Use user's timezone for "today" logic | UTC causes wrong-day bugs for conversation reset, habit completion, and streak tracking. All "today" checks must use user's IANA timezone. |
| Frequency-aware streaks | Streak logic must respect habit frequency | A weekly habit's streak shouldn't break on Tuesday. Daily = consecutive days. Weekly = completed this week. 3x_week = 3 completions in rolling 7 days. |
| Onboarding mentions habits | Ask about habits during setup | First session is the natural time to create habits alongside goals. "Any daily practices you want to maintain?" |
| Conversation size safety | Check JSON size before DynamoDB write | 20-turn cap + tool stripping should keep items under 400KB, but add a byte-size check with fallback trim as a safety valve. |

---

## Strategic Edges (Why Stride Wins)

### 1. SMS-Native = Zero Friction
Productivity apps lose 96% of users in 30 days. SMS has 98% open rate, zero install friction. The medium is the moat. No competitor combines AI + SMS + structured coaching.

### 2. Pattern Data Compounds Into a Moat
Week 1: "Plan realistically." Month 4: "You overcommit Mondays by 23%, your design estimates are 2x too optimistic, and each extra project cuts delivery by 15%." That's data no competitor can replicate without the same history. **This is why we add the 3 moat fields from day one.**

### 3. Push Beats Pull
"Just use ChatGPT" is the real threat — but ChatGPT waits for you to open it. Stride texts first. For freelancers and students, the push IS the product.

### 4. The Commitment Loop (Proven by Noom at Scale)
Weekly planning (commitment) → Daily check-in (accountability) → Weekly review (reflection) → Pattern insight (learning). This is the exact behavioral loop that Noom uses for health coaching. Stride applies it to productivity.

### 5. Price Undercut
Motion: $34/mo. Sunsama: $20/mo. Human coaching: $100+/mo. Stride: $12/mo. Gross margins of 52-73% are viable.

---

## Data Moat: Fields to Capture From Day One

Small schema additions that make Stride's pattern engine defensible over time:

**Task model** — add `status_changed_at: str` (ISO timestamp)
- Tracks: time-to-start, time-in-progress, task lifecycle duration
- Enables: "L tasks take 3 days before you start them. M tasks: started same day."

**Blocker model** — add `category: str` (external | scope | capacity | process)
- Agent picks category when calling `flag_blocker()`
- Enables: "70% of your blockers are external deps. Leave Monday headroom."

**Velocity model** — add `active_project_count: int`
- Snapshot of how many projects were active during that cycle
- Enables: "Each extra project drops your delivery by 15%. You're running 4."

**What this unlocks by month 4:**
- Estimation accuracy by task size ("Your L estimates are 40% too optimistic")
- Blocker resolution patterns ("Blockers sit 2 days on average before you address them")
- Context switching cost ("With 1 project: 90% completion. With 4: 40%")
- Overcommitment detection ("You overcommit every Monday, then recover Wednesday")
- Productivity rhythms ("You're most productive Wed-Thu mornings")

**Code cost:** ~30 lines across 3 files. Data value: irreplaceable.

### Tone Adaptation (Invisible Personalization)

Stride learns how to talk to each user without asking. This is a retention lever and a moat — can't be replicated without the same behavioral history.

**What Stride tracks:**
- Response latency to proactive messages (fast reply = that style resonated)
- Check-in verbosity (terse "done" vs detailed updates = direct vs conversational user)
- Reply rate by message type (which proactive messages get engagement?)
- Feedback sentiment (positive, neutral, frustrated)

**How it works:**
- Week 1: balanced default tone for everyone
- Week 2-3: Stride accumulates engagement signals
- Week 3+: `UserPattern.preferred_tone` updated (direct | encouraging | balanced)
- System prompt includes: "This user responds best to a {tone} coaching style"

**What changes per tone:**
- **Direct:** short, specific, numbers-focused. "3 tasks today. Wireframes is the big one — start there."
- **Encouraging:** celebrate wins, frame positively. "You finished the wireframes — that's momentum! What's next?"
- **Balanced:** mix of both (the default)

**Data captured:**
- `UserPattern.preferred_tone` — derived from behavior, updated every 2 weeks
- `OUTBOUND#{timestamp}` log already exists — add `replied_at` field when user replies, compute latency

**Sprint 3 scope:** Add `preferred_tone` to UserPattern, include it in system prompt, track response latency on outbound logs. The actual tone derivation logic (analyzing latency + verbosity patterns) ships as a simple heuristic first, gets smarter over time.

**Code cost:** ~20 lines (field + system prompt injection + latency tracking)

---

## Local Dev Tooling (Build First)

### chat.py — Interactive SMS Simulator

```
$ python chat.py +15551234567
Stride SMS Simulator (type 'quit' to exit)

You: hello
Stride: Welcome to Stride! I help you finish what you start.
        What are you working on?

You: Set up a project called Portfolio
Stride: Got it! I created Portfolio. What's the first task?
```

- Simulates full SMS guard chain (minus Twilio signature validation)
- Conversation memory persists between messages (tests the new feature)
- Consent auto-granted in local mode
- Runs against LocalStack DynamoDB
- **Files:** `chat.py` (gitignored, local dev only)

### POST /test-scheduler — Manual Scheduler Trigger

```
curl localhost:8000/test-scheduler
→ Scans users due for messages
→ Prints what would be sent (dry-run mode)
→ Optional: ?send=true to actually send via Twilio
```

- Tests timezone math, deduplication, user filtering
- No EventBridge dependency locally
- Add to local Flask server
- **Files:** `local_server.py` (gitignored)

---

## Phase Map

| Phase | Name | Timeline | Effort | Status |
|-------|------|----------|--------|--------|
| **Phase 0** | Pre-Build Fixes | First (before any new features) | ~2 hours | ✅ DONE |
| **Phase 1** | Foundation (models, tools, conversation memory, chat.py, tests) | Day 1 | ~1 day | ✅ DONE |
| **Phase 2** | Feedback + Onboarding | Day 2-3 | ~2 days | ✅ DONE |
| **Consolidation** | Single Lambda (stride-sms only) | — | ~1 hour | ✅ DONE |
| **Phase 3** | Proactive Messaging | Day 4-8 | ~5 days | ⏳ **Next** |
| **Phase 4** | Polish + Deploy | Day 9-12 | ~4 days | — |
| **Beta** | 10 free users | After A2P approval, ~1 month | — | — |
| **Sprint 4** | Team Version | After beta | ~14 days | — |
| **Sprint 5** | Payments (Stripe) | After team validated | ~10 days | — |

**Known bugs:** 1 — see `bugfix.md`. BUG-001 must be fixed as the first step of Phase 2.

### Phase 0 — Pre-Build Fixes ✅ DONE

Surgical fixes to existing tools that would cause bugs the moment we build Phase 1:

1. **`create_project`** — add `target_date` param (goal model needs deadlines)
2. **`list_active_projects`** — return `target_date` in response (agent can't reference deadlines without it)
3. **New `update_project` tool** — users need to adjust deadlines, names, descriptions without recreating
4. **`set_user_preference` tool** — moved from Phase 2; needed during onboarding when users say "I'm in California"
5. **`max_tokens` 512 → 1024** — system prompt is growing; 512 cuts off mid-thought during onboarding

**Files:** `shared/tools.py`, `functions/sms/handler.py`
**Detail:** See `phase0-fixes.md`

---

## Sprint 3 — Individual Beta-Ready (3 weeks)

### Pre-Build: Phase 0 Fixes ✅ DONE

All 5 fixes applied. See `phase0-fixes.md`.

### Week 1, Part 1: Core Foundation ✅ DONE (Phase 1)

#### 1. Conversation History Persistence ✅ DONE

- `CONVERSATION#CURRENT` DynamoDB entity per user
- `get_conversation()` / `save_conversation()` in `db.py`
- Tool payloads stripped, capped at 20 turns, 350KB safety check
- Timezone-aware weekly reset on user's `planning_day`
- **Files:** `shared/db.py`, `functions/sms/handler.py`

#### 2. User Preferences ✅ DONE

- `timezone`, `checkin_time`, `evening_time`, `planning_day` fields on User model
- `set_user_preference` tool — validates format, writes to `#METADATA`
- **Files:** `shared/models.py`, `shared/tools.py`

#### 4. Data Moat Fields ✅ DONE

- `Task.status_changed_at` — written on every `update_task_status()` call
- `Blocker.category` — enum: external | scope | capacity | process
- `Velocity.active_project_count` — computed from active projects at review time
- `UserPattern.preferred_tone` — default "balanced", injected into system prompt
- **Files:** `shared/models.py`, `shared/tools.py`

#### 5. Local Dev Tooling — chat.py ✅ DONE

- `chat.py` — interactive SMS simulator against LocalStack (gitignored)
- `/test-scheduler` endpoint: ⏳ Phase 2 (see below)

#### Habit Model + Tools ✅ DONE (added in Phase 1)

- `Habit` model — frequency: daily | weekdays | 3x_week | weekly
- `create_habit`, `complete_habit`, `list_habits` tools
- Frequency-aware streak logic (`_is_streak_alive`)
- Timezone-aware "done today" check

#### Tests ✅ DONE

- 104 tests across 6 test files: `test_models`, `test_tools`, `test_db`, `test_guards`, `test_conversation`, `test_streak`

---

### Week 1, Part 2: ✅ Phase 2 — Done

#### 3. Feedback Mechanism ✅ Done

**Collection (two paths):**
- **Keyword:** User texts `FEEDBACK <their thoughts>` → stored directly, no agent call, instant ack
- **Agent-prompted:** After weekly review, agent asks "Anything about Stride itself I could do better?" → calls `submit_feedback` tool

**Storage:** `USER#{user_id}` / `FEEDBACK#{ISO_timestamp}` — body, source, created_at

**Developer reads:** `make feedback` → DynamoDB scan → formatted table (dev-only, scan acceptable)

**Files:** `functions/sms/handler.py` (keyword in guard chain), `shared/tools.py` (new `submit_feedback` tool), `shared/db.py` (new `store_feedback()`), `Makefile`

#### 6. Better Onboarding + HELP ✅ Done

- One question at a time — no wall of text; SMS users drop off if overwhelmed
- HELP text: includes FEEDBACK keyword, reminder customization example, concise
- After first project, agent explains weekly rhythm (Monday plan / daily / Friday review)
- **Files:** `functions/sms/handler.py` (`_HELP_TEXT`, `_ONBOARDING_ADDENDUM`)

#### Tone Adaptation — Phase 2 Scope ✅ Done

Phase 2 scope is the bugfix only: `update_user_patterns` currently resets `preferred_tone`
to "balanced" on every weekly review (BUG-001). The fix preserves the existing value.

System prompt injection of `preferred_tone` is already in place (done in Phase 1).

Full tone derivation (latency tracking, heuristics, updating preferred_tone from behavior)
is deferred to Phase 3 — it requires outbound message logs that don't exist until the
scheduler Lambda is built.

**Files:** `shared/tools.py` (BUG-001 fix — 2 lines)

#### /test-scheduler Scaffold ✅ Done

- `GET /test-scheduler` in `local_server.py` — shows what message each user would receive
  based on their timezone + current time. Dry-run by default, `?send=true` for real send.
- Full implementation in Phase 3 when proactive consent + outbound SMS exist.
- **Files:** `local_server.py` (gitignored)

---

### Week 2: Proactive Messaging

The biggest differentiator. A to-do app waits. Stride texts first.

#### 7. Outbound SMS Helper

New `shared/sms.py` — wraps `twilio.rest.Client.messages.create()`. The `twilio` package (v9.4.0) is already in requirements.txt but only `RequestValidator` and `MessagingResponse` are imported today. No `Client` exists anywhere yet.

#### 8. Proactive Consent (TCPA)

Legally distinct from existing inbound consent. New entity: `USER#{user_id}` / `CONSENT#PROACTIVE`.

- During onboarding, Stride asks: "Want me to send you daily reminders? Reply REMIND ME"
- `REMIND ME` → sets proactive consent = active
- `NO REMINDERS` → revokes proactive consent
- `STOP` (existing) → revokes ALL consent including proactive
- Every outbound message includes "Reply NO REMINDERS to stop"

#### 9. Scheduler Lambda + EventBridge

```
EventBridge Scheduler (every 15 min, UTC)
    │
    ▼
stride-scheduler Lambda (256MB, 60s, ARM64)
    │
    ├── Scan users: proactive_consent=active, onboarded=true
    ├── For each user: convert preferred time to UTC, check 15-min window
    │
    ├── Weekly rhythm (spread across the week):
    │     ├── MONDAY AM (planning): "New week! You've got 3 projects and about 3 days
    │     │     of real work in you. What are you focusing on?"
    │     ├── TUE-THU AM (daily reminder): "Good morning! Today you planned:
    │     │     - Wireframes (a day or two) - Portfolio
    │     │     - Blog post draft (a few hours) - Blog"
    │     ├── TUE-THU PM (daily check-in): "How'd today go? Quick check-in."
    │     ├── WEDNESDAY (mid-week adjust): "Mid-week check: you've finished about
    │     │     a day's worth so far. Want to adjust your plan?"
    │     ├── FRIDAY PM (review/retro): "Week's wrapping up. You planned 5 days
    │     │     of work but finished 3 days worth. What would you do differently?"
    │     └── NUDGE (no activity 2+ days): "Haven't heard from you — everything ok?"
    │
    ├── Send via shared/sms.py
    └── Log: USER#{user_id} / OUTBOUND#{timestamp}
          (prevents double-send + tracks replied_at for tone adaptation)
```

**Timezone handling:** At beta scale (10-50 users), DynamoDB Scan is fine (~1 RCU). Scheduler does timezone math in Python. At 500+ users, migrate to `SCHEDULE#{utc_slot}` / `USER#{user_id}` entity for Query.

**Morning messages pull live data:** query user's active cycle tasks from DynamoDB, list today's planned work. No Claude call — just data formatting.

### User-Facing Language (Points Never Exposed)

The estimation model runs under the hood. Users see time-based language only:

| Internal | User sees (estimates) | User sees (capacity) |
|----------|----------------------|---------------------|
| S = 2 pts | "a few hours" | |
| M = 5 pts | "a day or two" | |
| L = 8 pts | "most of the week" | |
| XL = 13 pts | "more than a week" | |
| 15 pts/week avg | | "about 3 good days of real work" |
| 23 pts planned | | "that's almost 5 days of work" |

**Conversion formula for system prompt:** `days ≈ points / 5` (rough, not exact — Stride rounds naturally)

### Multi-Project Prioritization

During Monday planning, Stride:
1. Lists all active projects with their planned tasks (in time language)
2. Sums up total workload: "That's 7 days of work for a 5-day week"
3. References user's historical capacity: "You usually get about 3 days done"
4. Asks what to cut or shrink: "What can wait or get smaller?"

Users can add new projects anytime. Stride creates them immediately and includes them in the next planning session.

### Conversation Reset Timing

Conversation resets **Monday morning** (user's `planning_day`). This is after Friday's review data has been stored in DynamoDB (velocity, patterns, blockers). Monday's planning session starts fresh but has full access to all data via tools.

#### 10. Infrastructure (Terraform)

- New `eventbridge.tf`: Scheduler rule (rate: 15 min) → stride-scheduler Lambda
- New Lambda module in `lambda.tf` (same pattern as `stride-sms`)
- New ECR repo in `ecr.tf`: `stride-scheduler`
- Update `scripts/build_and_push.sh` for 4th function
- IAM: add `dynamodb:Scan` to existing `stride-lambda-exec` role
- New EventBridge execution role for scheduler → Lambda invoke

---

### Week 3: Polish + Deploy

#### 11. Testing + Edge Cases

- Conversation memory: test 20-turn cap, weekly reset, tool call stripping
- Proactive messaging: test timezone math, deduplication, consent flows
- Feedback: test keyword path and agent-prompted path
- Onboarding: test full flow end-to-end (new user → project → first check-in)

#### 12. Deploy + Smoke Test

- Deploy all changes via `make deploy` (CI/CD handles the rest)
- Set Twilio webhook URL in console → `{api_gateway_url}/sms`
- Real SMS round-trip: opt-in → onboarding → set preferences → create project → check-in → feedback → REMIND ME → verify morning message arrives

---

## Beta Plan (~1 month, 10 users)

- All features free, all features on
- Collect feedback via FEEDBACK keyword and agent-prompted feedback
- Developer reads feedback via `make feedback`
- Watch CloudWatch logs for errors, latency, cost spikes
- Key metrics to track: messages/user/day, check-in completion rate, which proactive messages get replies

---

## Sprint 4 — Team Version (after beta)

### Identity Model: Two Twilio Numbers

```
+1 (555) 000-0001 → Individual Stride
  Phone number = user_id
  Personal projects, personal coaching

+1 (555) 000-0002 → Team Stride (shared for ALL teams)
  Phone number → membership lookup → team_id
  Team projects, admin gets team summaries
```

- One A2P 10DLC campaign can use multiple numbers in its sender pool (up to 400)
- Cost: $1.15/mo for second number
- Each phone maps to exactly ONE team (via membership table). One team per person at SMS level.
- SMS handler for team number: same guard chain but routes via `TEAM#{team_id}` instead of `USER#{phone}`

### Team Data Model (Single-Table, TEAM# Namespace)

| Entity | PK | SK | GSI1PK | GSI1SK |
|--------|-----|-----|--------|--------|
| Team | `TEAM#{team_id}` | `#METADATA` | — | — |
| Membership | `TEAM#{team_id}` | `MEMBER#{user_id}` | `USER#{user_id}` | `TEAM#{team_id}` |
| Team Project | `TEAM#{team_id}` | `PROJECT#{project_id}` | `PROJECT#{project_id}` | `#METADATA` |

- Existing `gsi1` handles "list teams for a user" — no new GSI needed
- Admin = user who created the team (stored on Team metadata)
- DynamoDB is schemaless — new team entities coexist with individual entities, zero migration

### Team Invite Flow

```
Admin: "Add Sarah +15551234567 to my team"
    ↓
Sarah gets SMS on Team Stride number:
  "Hi! You've been invited to join
   [Design Team] on Stride by [Admin].
   Reply JOIN to accept."
    ↓
Sarah replies JOIN
    ↓
Sarah goes through consent → onboarding
    ↓
Sarah can use Team Stride for team projects
(If Sarah also wants personal Stride, she
texts the Individual number separately)
```

### Admin Capabilities

| Capability | Implementation |
|-----------|---------------|
| Create team | New `create_team` tool |
| Add members (by phone) | New `add_team_member` tool → SMS invite |
| Remove members | New `remove_team_member` tool |
| Set team goals | Existing `create_work_cycle` with team project |
| View team velocity | New `get_team_velocity` tool (aggregate) |
| View member check-ins | New `get_team_checkins` tool |
| View member feedback | Query `FEEDBACK#` items for team members |

### Admin Proactive Summaries (Agent-Generated)

Scheduler detects admin role → feeds team data to Claude → personalized summary:

```
"Morning! Design Team update:
 Sarah's crushing it — 3 of 5 done.
 Mike's been stuck on API docs since
 Wednesday. Worth a check-in?
 You've got the client proposal today."

Weekly:
"Team week: 34/50 pts completed (68%)
 Sarah: 15/18 pts — strong week
 Mike: 8/15 pts — blocked mid-week
 Pattern: Mike gets stuck on external deps.
 Want to do a team review?"
```

Cost: ~$0.01/summary. ~$3/mo for 10 teams.

### Tools Impact (6 of 13 need changes)

Tools that need team-awareness: `create_project`, `list_active_projects`, `create_checkin`, `update_user_patterns`, `complete_onboarding`, `get_user_patterns`. Plus ~5 new team-specific tools. All 7 db.py functions also need team variants.

### Infrastructure

- New Twilio number added to existing A2P campaign sender pool
- New or modified Lambda: `stride-sms-team` (separate handler for team number webhook) OR extend `stride-sms` to detect which Twilio number received the message
- Terraform: update API Gateway routes if new Lambda, or update SMS handler env vars

---

## Sprint 5 — Payments (after team validated)

### Stripe Integration

- New Lambda: `stride-stripe` at `POST /stripe-webhook`
- Validates Stripe webhook signature
- Handles: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
- New dependency: `stripe` Python package

### Subscription Model

- Entity: `USER#{user_id}` / `SUBSCRIPTION#CURRENT`
- Fields: stripe_customer_id, stripe_subscription_id, tier, status, trial_end, current_period_end

### Payment Flow (Stripe Payment Links — no web page)

1. User texts `UPGRADE` → Stride sends a Stripe Payment Link via SMS
2. User taps link → Stripe-hosted checkout → subscribes (14-day free trial)
3. Webhook: `checkout.session.completed` → writes `SUBSCRIPTION#CURRENT`
4. Trial ends → auto-charge → `status=active`
5. Payment fails → `status=past_due` → Stride sends friendly reminder
6. User texts `CANCEL` → Stride cancels via API → webhook confirms

### Pricing

- Individual: $12/mo
- Team: $12/seat/mo (admin pays, Stripe quantity = member_count including admin)
- 5-person team = $60/mo, 10-person team = $120/mo

### Feature Gating (decided after beta feedback)

Will decide what goes behind paywall after seeing what beta users value.

---

## Cost Projections

| Phase | Users | AWS | Claude API | Twilio | Stripe | Total | Revenue |
|-------|-------|-----|-----------|--------|--------|-------|---------|
| Beta (10) | 10 | ~$2 | ~$5 | ~$6 | $0 | **~$13/mo** | $0 |
| Individual (100, 30% paid) | 100 | ~$5 | ~$40 | ~$30 | $0 | **~$75/mo** | **$360/mo** |
| Teams (50 ind + 50 team) | 100 | ~$10 | ~$80 | ~$60 | ~$25 | **~$175/mo** | **$960/mo** |

**Cost optimization:** Anthropic prompt caching (system prompt identical across users). Static templates for proactive messages ($0 Claude cost). Agent-generated only for weekly planning/review/team summaries.

---

## What Exists vs What's Needed

| Feature | Status | Phase |
|---------|--------|-------|
| Inbound SMS + 10-step guard chain | ✅ Done | — |
| Lambda container image + ECR deploy (stride-sms only) | ✅ Done | deploy plan |
| CI/CD (GitHub Actions OIDC) | ✅ Done | — |
| 19 Strands tools | ✅ Done | Phase 0 + 1 + 2 |
| DynamoDB single-table (14 entities, 1 GSI) | ✅ Done | Phase 0 + 1 |
| `create_project` target_date param | ✅ Done | Phase 0 |
| `list_active_projects` returns target_date | ✅ Done | Phase 0 |
| `update_project` tool | ✅ Done | Phase 0 |
| `set_user_preference` tool | ✅ Done | Phase 0 |
| SMS handler max_tokens (512 → 1024) | ✅ Done | Phase 0 |
| Conversation memory (per-user, weekly reset) | ✅ Done | Phase 1 |
| Goal model (target_date + decomposition prompt) | ✅ Done | Phase 1 |
| Habit model + tools (create, complete, list) | ✅ Done | Phase 1 |
| Data moat fields (4 schema additions) | ✅ Done | Phase 1 |
| Timezone-aware date logic | ✅ Done | Phase 1 |
| Frequency-aware habit streaks | ✅ Done | Phase 1 |
| User preferences (timezone, times, planning_day) | ✅ Done | Phase 1 |
| chat.py SMS simulator | ✅ Done | Phase 1 |
| Unit + integration test suite (104 tests) | ✅ Done | Phase 1 |
| BUG-001: preferred_tone reset fix | ✅ Done | Phase 2 |
| Feedback collection (keyword + tool + make command) | ✅ Done | Phase 2 |
| Better onboarding + HELP | ✅ Done | Phase 2 |
| Tone adaptation — preferred_tone bug fix | ✅ Done | Phase 2 |
| /test-scheduler scaffold endpoint | ✅ Done | Phase 2 |
| Outbound SMS helper (shared/sms.py) | — Phase 3 | Phase 3 |
| Proactive consent (CONSENT#PROACTIVE, TCPA) | — Phase 3 | Phase 3 |
| EventBridge scheduler Lambda | — Phase 3 | Phase 3 |
| Morning/evening/weekly proactive messages | — Phase 3 | Phase 3 |
| Tone derivation (latency tracking + heuristics) | — Phase 3 | Phase 3 |
| Team data model + tools | — Sprint 4 | Sprint 4 |
| Second Twilio number | — Sprint 4 | Sprint 4 |
| Admin capabilities + summaries | — Sprint 4 | Sprint 4 |
| Stripe payments | — Sprint 5 | Sprint 5 |

---

## SMS Design Principles (Non-Negotiable for Quality)

Research from health coaching apps (Noom, Lark) and SMS marketing data:

1. **Sub-60-second check-ins.** If daily check-in takes >1 minute, users stop replying. Keep it to 3 questions, accept terse answers.

2. **160-char awareness.** SMS segments are 160 chars. Every extra segment costs $0.0079. Keep Stride's responses punchy — 1-2 segments max for proactive messages. Agent responses can be longer but the system prompt should enforce brevity.

3. **Personality over formality.** "Sarah's crushing it" beats "Sarah completed 3 of 5 tasks." Stride is a coach, not a dashboard. The agent-generated approach ensures this.

4. **Never nag, always invite.** "Haven't heard from you — everything ok?" not "You missed your check-in." Nudges should feel caring, not guilt-inducing.

5. **One question at a time over SMS.** Don't send a wall of text. Onboarding asks one question, waits for reply, asks the next. This is why conversation memory is critical.

6. **Celebrate wins explicitly.** "You finished the wireframes — nice work!" not just "Task marked done." Positive reinforcement drives engagement more than accountability pressure.

---

## Competitive Landscape (Research Summary)

| Competitor | Price | Model | Why Stride Wins |
|-----------|-------|-------|----------------|
| Motion | $19-34/mo | App, AI auto-scheduling | No coaching, no accountability, no SMS |
| Sunsama | $20-26/mo | App, daily planning ritual | App-based (96% churn), no pattern insights |
| Coach.me | $25-100/mo | App + human coaching | Human coaches don't scale, expensive |
| Focusmate | $5-10/mo | Video body-doubling | Not async, not coaching, scheduling-based |
| ChatGPT | $20/mo | Pull model (user opens it) | No push, no structured sessions, no data persistence |
| Noom (health) | $32-59/mo | SMS/app coaching | Health only — proves the model works for coaching |

**Gap:** No product combines AI + SMS + structured productivity coaching + pattern insights. Stride owns this space.

# Research: Multi-Context Identity for SMS-Based Products

## 1. How Messaging Platforms Handle Workspace Switching

### Slack

**The problem:** Slack originally assumed users belonged to a single workspace. When Enterprise Grid (2017) allowed large orgs to run multiple workspaces, users increasingly needed to be in several simultaneously. This caused context-switching friction and missed notifications.

**What they built:**
- **Unified Grid** (shipped March 2024): A complete re-architecture that provides a single unified view of all data a user can access across workspaces, rather than maintaining separate workspace-scoped views.
- The sidebar shows all workspaces; users can filter by workspace but default to seeing everything.
- Keyboard shortcut (Cmd+Shift+S) opens the workspace switcher.
- Cross-workspace channels allow conversations to span multiple workspaces without duplication.

**Key technical patterns:**
1. **Workspace-agnostic APIs**: Queries sharded by channel ID don't care which workspace they belong to.
2. **Explicit workspace selection**: For operations like channel creation, the user specifies the target workspace.
3. **Iterative workspace querying**: Backend queries across all of a user's workspaces (capped at 50).

**Lesson learned:** "The architecture of an application drifts far enough from how that application is used" -- they treated the migration as a company-wide priority, not an isolated engineering effort.

**Relevance to SMS:** Slack has a rich UI with sidebars, tabs, and dropdowns. None of this translates to SMS. The key takeaway is that even Slack found multi-workspace painful with a full GUI. In SMS, it would be dramatically worse.

### WhatsApp Business

**Model:** One phone number = one WhatsApp Business Account. Period. You cannot use the same phone number for multiple WhatsApp Business accounts.

**Multi-account on device:** WhatsApp now allows two accounts on Android (each needs its own phone number/SIM). This is for personal vs work separation, not multi-workspace.

**Business platform side:** Platforms like Braze can manage up to 10 WhatsApp Business accounts per workspace, but each account has its own dedicated phone number. The workspace is the management layer; the phone number is the identity layer.

**Relevance to SMS:** WhatsApp's answer to multi-context is unambiguous: separate numbers. They never attempted to solve multi-context on a single number.

### Community App (celebrity/creator SMS platform)

**Model:** Each creator (Leader) gets a dedicated 10-digit phone number. Fans text that number to opt in. The phone number IS the brand identity. There is no concept of one number serving multiple creators or contexts.

**Relevance to SMS:** The largest SMS-first consumer product chose one number per context, not context-switching on a shared number.

---

## 2. How SMS-Based SaaS Products Handle Multi-Tenant Identity

### The universal pattern: phone number = identity, not context

Every SMS-based product I found treats the phone number as a fixed identity anchor, not a switchable context handle. The patterns break down into:

**Pattern A: One inbound number, one context (most common)**
- The product has a single phone number.
- Users text it. Their phone number identifies them.
- There is no concept of "workspaces" or "teams" -- the product is single-context.
- Examples: Community app, most SMS chatbots, SMS marketing platforms.

**Pattern B: One inbound number per team/department (business SMS platforms)**
- Products like Clerk Chat, Falkon SMS, YakChat, and SimpleTexting assign dedicated numbers per team, department, or location.
- A sales team gets one number. Support gets another. HR gets another.
- The inbound number determines the routing context, not user commands.
- SimpleTexting explicitly offers "multi-number" as a feature: different numbers for different purposes, managed from one dashboard.

**Pattern C: Subaccounts with isolated numbers (multi-tenant SaaS)**
- Twilio's recommended pattern for multi-tenant apps: one subaccount per customer/tenant.
- Each subaccount gets its own phone numbers, isolated from other tenants.
- The parent account manages throughput allocation across subaccounts.
- This is the pattern used by platforms like HighLevel, OpenPhone, and other white-label SMS tools.

### What nobody does: context-switching commands on a single number

I could not find a single production SMS product that handles multi-workspace by having users text commands like "SWITCH TO Team X" or "USE Project Y" on the same number. This pattern does not appear to exist in the wild.

---

## 3. Twilio Best Practices for Multi-Context SMS Applications

### Twilio's explicit recommendation: subaccounts for multitenancy

From Twilio's own documentation:
- "This is easier to do if you use subaccounts for multitenancy."
- Subaccounts allow you to "segment each of your customers' use of Twilio and keep it separate from all the rest."
- Each subaccount gets its own Account SID, phone numbers, and usage tracking.
- Phone numbers can be transferred between subaccounts.

### Multiple numbers vs. single number

Twilio does NOT recommend "snowshoeing" (adding many long-code numbers to a single Messaging Service to distribute load). But they explicitly support multiple numbers for different use cases.

**Twilio's messaging service model:**
- A Messaging Service can contain multiple phone numbers in its sender pool.
- A Messaging Service can only be linked to one A2P 10DLC Campaign at a time.
- Different use cases (marketing vs transactional vs customer care) should be separate campaigns.

**Best practice from third-party analysis:**
> "Rather than combining disparate purposes in one 'Mixed' campaign, separate marketing from transactional traffic onto distinct campaigns when feasible. This isolates risk if one channel faces carrier filtering."

### Routing different products/features to different numbers

Twilio supports this natively:
- Each phone number can have its own webhook URL configured.
- Inbound SMS to Number A can route to Lambda A; inbound SMS to Number B can route to Lambda B.
- This is the simplest, most reliable routing pattern -- no parsing, no ambiguity, no state management.

---

## 4. Patterns for "Workspace Switching" in Text-Message Apps

### Pattern 1: Separate numbers (dominant pattern)

How it works: Each workspace/team/context gets its own phone number. The user texts the number for the context they want. No switching needed -- the number IS the context.

**Pros:**
- Zero ambiguity. The user's contact list is the "workspace switcher."
- No state management needed on the server side.
- No risk of messages going to the wrong context.
- TCPA consent is per-number, keeping compliance clean.
- Each number can have its own webhook, simplifying routing.

**Cons:**
- Users manage multiple contacts (but they already do this for every other service).
- Additional phone number cost ($1.15/mo per number on Twilio).
- If different A2P campaigns are needed, additional campaign fees.

### Pattern 2: Keyword prefix routing (theoretical -- not found in production)

How it would work: User texts "TEAM: [message]" or "#projectname [message]" to a single number. Server parses the prefix and routes accordingly.

**Why nobody does this:**
- SMS has no autocomplete, no syntax highlighting, no error correction.
- Users will forget the prefix, misspell it, or format it wrong.
- Every message requires cognitive overhead.
- Error handling is painful ("Did you mean Team Alpha or Team Alfa?").
- The "default context" problem: what happens when there's no prefix?

### Pattern 3: Stateful context with explicit switching (theoretical)

How it would work: User texts "SWITCH Team Alpha" to change their active context. All subsequent messages go to that context until they switch again.

**Why this is risky:**
- Invisible state. Users forget which context they're in.
- Accidental messages to the wrong team/project with no visual indicator.
- Time-based sessions add complexity (does context expire? after how long?).
- Recovery UX is awkward ("You sent a daily check-in to Team Alpha, did you mean Team Beta?").

### Pattern 4: Bot-initiated disambiguation (AI-powered)

How it would work: The AI agent infers context from message content. If ambiguous, it asks: "I see you have two active projects. Is this about Project X or Project Y?"

**Pros:** Most natural feeling for the user.
**Cons:** Adds latency, costs an extra LLM call for disambiguation, and will guess wrong sometimes.

---

## 5. Twilio Pricing for Additional Phone Numbers

### Phone number costs

| Item | Cost |
|---|---|
| Local phone number (10DLC) | $1.15/month |
| Toll-free number | $2.15/month |

### A2P 10DLC registration costs

| Item | Cost |
|---|---|
| Brand registration (Standard) | $44 one-time (includes vetting) |
| Brand registration (Low-Volume Standard) | $4.50 one-time |
| Brand registration (Sole Proprietor) | $4.50 one-time |
| Campaign vetting fee | $15 one-time per campaign |
| Standard Campaign monthly | $10/month |
| Low-Volume Mixed Campaign monthly | $1.50/month |
| Sole Proprietor Campaign monthly | $2/month |

### Per-message carrier surcharges (registered)

| Carrier | SMS | MMS |
|---|---|---|
| AT&T | $0.002 | $0.0035 |
| T-Mobile | $0.003 | $0.01 |
| Verizon | $0.0025 | $0.005 |

Unregistered per-message fees are 5-10x higher.

---

## 6. A2P 10DLC: Can One Campaign Use Multiple Phone Numbers?

**Yes.** Here is the structure:

```
Brand (1 per business)
  └── Campaign (up to 5 per brand for Standard/LVS)
        └── Messaging Service (1 per campaign)
              └── Sender Pool (multiple phone numbers allowed)
```

**Key rules:**
- A phone number can only belong to one Campaign at a time.
- A Messaging Service can only be linked to one Campaign at a time.
- A Standard/Low-Volume Standard Campaign can have up to **400 phone numbers** in its sender pool.
- A Sole Proprietor Campaign is limited to **1 phone number**.
- A Brand can have up to **5 Campaigns**.

**What this means for Stride:**
- You can register one Brand (Stride).
- Under that Brand, you can have up to 5 Campaigns.
- If all of Stride's messaging is a single use case ("productivity coaching"), one Campaign with a "Low-Volume Mixed" type ($1.50/month) covers it.
- You can add multiple phone numbers to that single Campaign's Messaging Service.
- Adding a second number for team/workspace routing would cost $1.15/month for the number, but NO additional campaign fee if it's the same use case.
- If team messaging is a materially different use case, you'd register a second Campaign ($15 one-time + $1.50-$10/month).

---

## 7. Twilio's Recommendation: Different Numbers vs. Same Number for Different Features

Twilio does not publish a single opinionated "do this" document. But the guidance across their docs points clearly in one direction:

**Use separate numbers when:**
- Different use cases need different compliance handling (marketing vs transactional).
- You want clean webhook routing without message parsing.
- Multi-tenant isolation is needed (subaccounts + dedicated numbers).
- Different departments/teams need identifiable inbound numbers.

**Use same number + Messaging Service when:**
- You need to scale throughput by pooling numbers.
- All messages serve the same use case and compliance bucket.

**The Address Configuration API** explicitly exists for routing inbound messages differently based on which number received them, reinforcing that Twilio's architecture is built around number-level routing.

---

## Synthesis: What This Means for Stride

### The industry consensus is clear

Every real production system that handles multi-context SMS uses **separate phone numbers** as the context boundary. Nobody ships keyword-prefix routing or stateful context switching over SMS.

### The cheapest viable path for Stride teams

If Stride adds team/workspace support:

1. **Each workspace gets its own Twilio phone number** ($1.15/month each).
2. All numbers can live under the **same A2P 10DLC Campaign** if the use case is the same (productivity coaching), so no additional campaign registration fees.
3. Each number gets its own **webhook URL**, routing to the same Lambda but with context (the inbound `To` number identifies the workspace).
4. Users save each workspace number as a separate contact ("Stride - Personal", "Stride - Acme Team").
5. TCPA consent is managed per-number, per-user -- clean and compliant.

### Cost projection for teams tier

| Item | Cost |
|---|---|
| Base number (personal) | $1.15/month (already have) |
| Team workspace number | $1.15/month per workspace |
| 5-person team, 1 workspace | $1.15 additional = $2.30 total |
| 10-person team, 3 workspaces | $3.45 additional = $4.60 total |
| Campaign fee (same use case) | $0 additional |
| Campaign fee (if separate use case) | $15 one-time + $1.50-$10/month |

At the $50-100/mo team pricing, Twilio number costs are negligible.

### What to avoid

- Do NOT build keyword-prefix routing ("TEAM: message"). No production product does this.
- Do NOT build stateful context switching ("SWITCH Team Alpha"). Invisible state causes wrong-context messages.
- Do NOT try to have the AI agent disambiguate context on every message. It adds latency and cost.

### The one exception worth considering

For the **solo user with multiple personal projects** (not teams), AI-powered context inference is reasonable:
- The agent already knows the user's active projects.
- Daily check-ins are inherently project-scoped -- the agent can ask "which project?" when ambiguous.
- This is a conversational interaction, not a routing problem.
- This is what Stride already does (or will do) -- no architecture change needed.

The multi-number pattern is specifically for **multi-tenant/team** scenarios where different people share a workspace.

---
---

# Research: Competitive Landscape & Strategic Moats for Stride

*Conducted March 2, 2026*

---

## 1. Direct Competitors

### A. SMS-Based Coaching/Productivity Tools

The SMS-based productivity coaching space is remarkably thin. There is no dominant SMS-first AI productivity coach in market.

**Shine (now Shine app)**
- Started as SMS-only daily motivational texts (2016). Pivoted to an app.
- Originally free daily texts, then launched "Shinevisor" -- paid tier connecting users to certified life coaches via text.
- The pivot to app is telling: pure SMS was not enough to retain users or monetize at scale.
- Lesson for Stride: SMS is a great acquisition and engagement channel, but they found they needed richer interaction for monetization.

**TextCoach**
- Licensed therapists ("Coaches") via text messaging platform.
- B2B distribution: sold through CuraLinc Healthcare's EAP programs, not direct to consumer.
- Pricing not publicly disclosed -- enterprise/insurance-funded model.
- Not a competitor for individual productivity coaching. It is therapy, not goal-tracking.

**Lark Health**
- AI health coaching via chat (in-app, not SMS).
- Covers weight management, diabetes, hypertension.
- Funded through health insurance/EAP -- free to qualifying users.
- Interesting precedent: proved that AI chat coaching can drive health outcomes. But it is health-domain, not productivity.

**Key finding:** No one is doing what Stride does -- AI-powered productivity coaching delivered via SMS to individuals. The closest analogues are in health/wellness, and most have either pivoted to apps or gone B2B/insurance-funded.

### B. AI Productivity Coaches (App-Based)

**Motion** -- $19/mo annual, $34/mo monthly
- AI auto-schedules your day by fitting tasks into calendar gaps.
- Moat: calendar integration depth. It needs your full calendar to work.
- What users hate: price jumps on feature upgrades, cancellation/billing complaints (auto-renewal traps, unresponsive support), steep learning curve.
- No free tier. Premium-only positioning.
- Key weakness: purely reactive scheduling. No coaching, no pattern recognition, no "you overcommit every Monday" feedback.

**Sunsama** -- $20/mo annual, $26/mo monthly
- "Mindful daily planner" -- deliberate, slow planning ritual each morning (10-15 min).
- Moat: the ritual itself becomes habit. Users who stick with the morning planning feel dependent on it.
- What users hate: price ($200/yr feels high for a planner), slow feature development, too much ceremony for some.
- Key weakness: requires significant daily time investment. Not async-friendly. No AI coaching or pattern insights.

**Reclaim.ai** -- Free tier, $8/mo Starter, $10/mo Business, $18/mo Enterprise
- AI calendar optimization, habit scheduling, focus time protection.
- Moat: deepest free tier in the space. Hard to leave because it is managing your calendar.
- What users hate: no native mobile app (major gap), limited integrations, some notification quirks, no iCloud Calendar.
- Key weakness: optimizes time blocks, does not coach on behavior or patterns.

**Coach.me** -- Free community tier, $25/week for human coaching
- Habit tracking + marketplace of human coaches.
- Has been in "rebuilding foundations" mode for 2 years. Not innovating.
- Moat: coach marketplace network effect (but small).
- Key weakness: human coaching at $100+/mo is expensive. AI coaching component is minimal.

**Rocky.ai** -- Free tier (limited), $15.99/mo Personal Boost
- Daily 5-minute AI coaching chats. Leadership and soft skills focus.
- Features: role-play simulations, motivational analysis, reflections.
- Key weakness: enterprise/leadership focused, not individual productivity. Chat interactions become repetitive.

**Focusmate** -- Free (3 sessions/week), paid for unlimited
- Virtual body-doubling: pairs you with a stranger on video for 25/50/75-min work sessions.
- Moat: the social accountability and community. Users report 161% productivity increase (self-reported, ADHD users especially).
- Key weakness: requires scheduling video sessions. Not async. Not AI-powered.

### C. Competitive Pricing Summary

| Product | Free Tier | Paid Price | What You Get |
|---|---|---|---|
| Motion | None | $19-34/mo | AI auto-scheduling |
| Sunsama | 14-day trial | $20-26/mo | Mindful daily planning ritual |
| Reclaim.ai | Yes (generous) | $8-18/mo | AI calendar optimization |
| Coach.me | Yes (community) | $100+/mo | Human coaching |
| Rocky.ai | Yes (limited) | $15.99/mo | AI leadership coaching |
| Focusmate | Yes (3/week) | Paid tier available | Virtual coworking accountability |
| **Stride (planned)** | **TBD** | **$10-15/mo** | **AI productivity coaching via SMS** |

**Stride's pricing sweet spot:** $10-15/mo undercuts Motion and Sunsama, matches Reclaim's paid tier, and is dramatically cheaper than human coaching. This price point is viable if Claude API costs per user stay under $3-5/mo.

---

## 2. Indirect Competitors

### A. Todoist / Asana / Linear AI Features

These tools are adding AI but it is assistive, not coaching:

**Todoist** (2025-2026):
- AI Assistant on Pro plan: task suggestions, intelligent scheduling, priority recommendations.
- "Todoist Assist": natural language and voice input for task management.
- Still a task manager at core. AI makes input easier, does not coach behavior.

**Asana**:
- AI for task assignments, progress tracking, timeline visualization.
- Team-focused. AI helps manage the project, not the person.

**Linear**:
- Integration-first approach. Works with Reclaim, Jira, etc.
- Developer-focused issue tracker. No coaching layer.

**Why these are NOT Stride competitors:** They optimize task management. Stride optimizes the person. A user would use Todoist AND Stride -- Todoist to track what they need to do, Stride to coach them on how they actually work. They are complementary, not competitive.

### B. ChatGPT / Claude as DIY Productivity Coach

This is the real indirect competitor. Anyone can prompt ChatGPT to "be my productivity coach."

**Why people would still pay for Stride:**

1. **Persistence.** ChatGPT does not remember your history across sessions (unless you manually manage it). Stride accumulates weeks/months of pattern data automatically.

2. **Proactive outreach.** ChatGPT waits for you to open it. Stride texts you. The push model is critical -- people who need coaching the most are the ones least likely to initiate it.

3. **Structure.** ChatGPT gives you whatever you ask for. Stride runs structured sessions (daily check-in, weekly review, planning). Structure drives consistency.

4. **Pattern recognition.** After 4 weeks of data, Stride can say "You've underestimated tasks by 40% three weeks in a row." ChatGPT cannot do this without you manually feeding it your history every session.

5. **No setup required.** Text a number, answer questions. No prompt engineering, no context window management, no "act as a productivity coach" preamble.

6. **SMS channel.** 98% open rate. You cannot ignore a text the way you ignore an app notification or a ChatGPT tab.

**The honest counter-argument:** Power users who enjoy prompt engineering may never pay. That is fine. Stride's target users (freelancers, students, creatives) want the coaching to come to them, not to build it themselves.

---

## 3. Why SMS Is Sticky vs. Apps

### Hard Data: SMS vs. App Engagement

| Metric | SMS | App Push Notifications |
|---|---|---|
| Open rate | 98% | 10.7% Android, 8% iOS |
| Average read time | Within minutes | Hours (if ever) |
| Click-through rate | ~8% | ~7.8% average |
| Day-30 retention | N/A (no app to abandon) | 4.1% for productivity apps |

### App Abandonment Is Catastrophic for Coaching Products

- **25%** of users abandon an app after a single use.
- **71%** stop using an app within 90 days.
- Productivity apps specifically: 17.1% day-1 retention, dropping to **4.1% by day 30**.
- Health/wellness apps: 70% discontinue within 100 days.

**This is Stride's single strongest strategic argument.** If Stride were an app, it would lose 96% of users within a month by industry averages. As SMS, there is no app to delete, no notification to disable, no login to forget.

### Why SMS-First Products Chose SMS

**Shine (2016):** Launched SMS-only because "texting doesn't depend on algorithms or app engagement -- it gives you a direct line to your audience." Eventually added an app for richer features but kept SMS as the engagement anchor.

**Key insight from coaching industry research:** SMS read rates of 55%+ (conservative) with near-instant visibility make it the most effective channel for coaching interactions that require consistency and follow-through.

### The SMS Cost Trade-Off

SMS is not free. Per-message costs matter at scale.

| Volume | Per-Message Cost (Twilio + carrier) | Monthly Cost |
|---|---|---|
| 10 msgs/day (heavy user) | ~$0.011 total | ~$3.30/user/mo |
| 5 msgs/day (average user) | ~$0.011 total | ~$1.65/user/mo |
| 2 msgs/day (light user) | ~$0.011 total | ~$0.66/user/mo |

At $10-15/mo subscription price, SMS costs are 10-20% of revenue per user. Manageable, but something to watch as message volume grows. Message segmentation (>160 chars = multiple segments billed separately) is the hidden cost driver -- Stride's responses need to be concise.

---

## 4. Moat Opportunities for Stride

### A. The Pattern Data Moat

**What Stride accumulates that gets more valuable over time:**

1. **Estimation accuracy data.** Every task has an estimate (S/M/L/XL) and an actual outcome. After 20+ tasks, Stride knows your personal estimation bias. This data does not exist anywhere else.

2. **Commitment vs. completion ratios.** Weekly: "You committed to 30 points but completed 18." Over months, this reveals your sustainable pace -- your actual capacity, not what you think it is.

3. **Blocker patterns.** What blocks you? Time of week? Type of task? External dependencies? This emerges only from longitudinal data.

4. **Overcommitment triggers.** Do you overcommit on Mondays (fresh energy, unrealistic optimism)? Do you drop tasks every Friday? Patterns emerge over 4-8 weeks.

5. **Project type performance.** Are you better at creative tasks or administrative ones? Do you estimate design work well but underestimate writing?

**Why this is a real moat:** This data is personal, longitudinal, and impossible to recreate elsewhere. If a user has 6 months of pattern data in Stride, switching to a competitor means starting from zero self-knowledge. No export can transfer "you underestimate writing tasks by 60%."

**How fitness/health apps prove this model:**
- Whoop's moat is your 12+ months of strain/recovery data. Switching to another wearable loses all your baselines.
- Noom tracks engagement across 6 categories (weigh-ins, articles, coaching messages, meals, exercise, group posts). Users who engage across more categories retain longer.
- Strava's moat: your complete running/cycling history and social graph. Switching means losing your PR history and friend network.

**Actionable for Stride NOW:**
- Store every estimate, every completion, every blocker, every plan-vs-actual delta from day one.
- Surface pattern insights starting at week 4 ("I've noticed you tend to...").
- Make these insights visible in weekly reviews -- users must feel their data working for them.

### B. Switching Costs

**Productivity tool switching costs are generally LOW** -- most tools allow data export, and task lists are simple to recreate. But Stride's switching cost is different:

1. **Behavioral insights cannot be exported.** Even if you export your task history, the patterns and personalized coaching calibration do not transfer.

2. **Habit formation.** If someone has built a habit of texting Stride every morning, that habit is tied to the phone number, the rhythm, and the personality of the AI. Switching means rebuilding the habit.

3. **Relationship with the coach.** This sounds soft, but it is real. Noom's research shows that coach engagement is the #1 driver of retention and outcomes. If Stride's AI develops a "voice" that the user trusts, switching feels like losing a coach.

### C. Network Effects in Team Version

Productivity tools have **weak direct network effects** but **strong intra-company network effects**:

- Stride for teams: if 3 out of 5 team members use Stride, the remaining 2 get pressure to join (the team's velocity data is incomplete without them).
- Cross-team visibility creates value: "Your team completed 85% of commitments this week, up from 72%."
- The more team members, the more accurate the team patterns and the harder it is to rip out.

**This is a Sprint 3+ concern.** For now, solo user moat (pattern data) is the priority.

---

## 5. Design Patterns from Successful Coaching Products

### A. Noom's Behavioral Science Framework

Noom employs three therapeutic frameworks: CBT (cognitive behavioral therapy), ACT (acceptance and commitment therapy), and DBT (dialectical behavioral therapy). Their key engagement mechanisms:

1. **Daily coach check-ins.** Coaches check in daily using motivational interviewing.
2. **Micro-actions.** Small, completable actions that build momentum. "Go micro for big results."
3. **Streaks and levels.** Gamification to make habit formation tangible.
4. **Multi-signal engagement.** Users who engage across multiple activities (logging, reading, messaging, weighing) retain dramatically better.
5. **The 4-C model:** Cognitive, Commitment, Community, and Coach -- layered engagement touchpoints.

**What Stride can steal from Noom:**
- Daily check-in as the non-negotiable engagement anchor (already designed).
- Multi-signal tracking: log a check-in + complete a task + respond to a review = higher engagement signal.
- Surface streaks: "You've checked in 12 days in a row" -- simple but powerful.
- Challenge overcommitment (Stride already does this) -- this maps directly to Noom's "cognitive" pillar of surfacing thinking patterns.

### B. Commitment Devices and Accountability

Research findings on what makes people actually follow through:

1. **Social commitment devices** are the most effective for socially-motivated people. Telling someone else your goal increases completion by approximately 30% (Gine, Karlan, Zinman 2010).

2. **Written behavioral contracts** produce measurable outcome improvements (1.5 kg more weight loss in studies).

3. **Coaching as commitment device:** "Not wanting to let someone down and the desire to keep commitments to an accountability partner have proven to be powerful motivators."

4. **The accountability effect:** The mere act of reporting to someone (human or AI) changes behavior. Stride's daily check-in is a commitment device -- you said you would do X, now Stride is asking if you did.

**Actionable for Stride NOW:**
- The weekly planning session IS a commitment device. Frame it as: "You're committing to these tasks this week."
- The daily check-in IS accountability. "Yesterday you said you'd finish the wireframes. Did you?"
- The weekly review IS reflection. "You committed to 5 tasks, completed 3. What happened?"
- Do NOT add financial stakes or gamification gimmicks. The coach relationship and the commitment-ask-review loop is the mechanism.

### C. What Makes People Complete Goals vs. Abandon Them

Key factors from research:

1. **Early momentum matters most.** MyFitnessPal research: behavior in the first 7 days predicts long-term success. If Stride's onboarding week does not feel valuable, users are gone.

2. **Realistic goal-setting.** The #1 reason people abandon: they set goals that are too ambitious and get demoralized. Stride's size-limiting (flagging XL as scope risk) and overcommitment challenges are exactly the right intervention.

3. **Visible progress.** Users who can see their progress (completion rates, streaks, velocity trends) persist longer than those who cannot.

4. **Consistency over intensity.** Daily micro-engagements (Stride's 3-question check-in) beat weekly deep sessions. The check-in must be fast and frictionless.

5. **Pattern awareness creates motivation.** When users see "you completed 80% this week, up from 60% last week," it creates intrinsic motivation. Numbers without context (raw task counts) do not.

---

## 6. Pricing Intelligence

### A. What SMS-Based Coaching Products Charge

| Product | Model | Price |
|---|---|---|
| Shine | Free daily texts + paid human coaching tier | Free / premium (price not public) |
| TextCoach | B2B/insurance-funded | Not consumer-facing |
| Lark Health | Insurance-funded | Free to qualifying users |
| Rocky.ai | Freemium | Free / $15.99/mo |
| Noom Weight | Subscription (aggressive trial-to-paid) | $17-42/mo depending on commitment |
| Coach.me | Free community + paid human coaches | Free / $25/week human coaching |

### B. Willingness to Pay for Productivity Coaching

- **Human coaching:** $100-400/mo is standard for individual productivity/accountability coaching.
- **AI coaching apps:** $10-20/mo is the established range (Rocky at $16, Noom at $17-42, Motion at $19-34).
- **Stride's $10-15/mo target** is at the low end of AI coaching apps and roughly 10% of human coaching cost. This is a strong value proposition.

### C. Freemium vs. Trial vs. Paid-Only

| Model | Typical Conversion | Best For |
|---|---|---|
| Freemium | 3-5% (6-8% exceptional) | Products where free users generate data or network value |
| Free trial (no card) | 10-15% | Products that need demonstration time |
| Free trial (card required) | 30-60% | Products confident in their hook |
| Paid-only | Highest ARPU, lowest volume | Premium positioning (Motion) |

**Recommendation for Stride:**

**Start paid-only with a 14-day free trial (no card required).** Rationale:
1. SMS has per-message costs. Freemium users cost money every time they text.
2. Unlike an app where free users cost near-zero to serve, every Stride interaction has a Claude API cost + Twilio SMS cost. Free users are expensive.
3. The 14-day trial lets users experience the full planning-checkin-review cycle (2 full weeks) before deciding.
4. Collect card at end of trial, not upfront. This is a consumer product for freelancers and students -- card-upfront friction is too high for initial traction.
5. Target 10-15% trial-to-paid conversion. At $12/mo, you need ~100 trial users per month to get to $120-180 MRR for initial validation.

### D. Unit Economics Sketch (Per User, Per Month)

| Cost Item | Estimate |
|---|---|
| Claude API (5 agent calls/day avg, ~1K tokens each) | $2-4/mo |
| Twilio SMS (5 messages/day avg, inbound + outbound) | $1.50-3.00/mo |
| DynamoDB (reads/writes for history, patterns) | <$0.10/mo |
| Lambda compute | <$0.05/mo |
| **Total COGS per user** | **$3.65-7.15/mo** |
| **Revenue per user** | **$10-15/mo** |
| **Gross margin** | **52-73%** |

The Claude API cost is the wild card. Prompt caching, response compression (keep SMS short), and capping history at 20 turns (already designed) are the levers.

---

## 7. Synthesis: Stride's Strategic Edges

### What Stride has that nobody else does (right now):

1. **SMS-native AI coaching.** No competitor combines AI + SMS + structured productivity coaching. Health apps (Lark, Noom) do AI + chat for health. Motion/Sunsama do AI + app for scheduling. Nobody does AI + SMS for productivity.

2. **Zero-install, zero-login engagement.** 98% open rate channel. No app store, no password, no download. Just text.

3. **Proactive push model.** Stride initiates. ChatGPT waits. This is the fundamental difference from every general-purpose AI assistant.

4. **Pattern data that compounds.** Every week makes the coaching more accurate and the switching cost higher.

5. **Price undercut.** At $10-15/mo, Stride is cheaper than Motion ($19-34), Sunsama ($20-26), and dramatically cheaper than human coaching ($100+/mo).

### What Stride must build to defend these edges:

1. **Ship pattern insights by week 4.** The moat only works if users SEE their patterns surfaced. Sprint 3's "pattern auto-update" is strategically critical -- do not defer it.

2. **Keep check-ins fast.** The daily check-in must take <60 seconds. If it feels like homework, users will ignore the texts.

3. **Concise SMS responses.** Every message over 160 chars costs double. But more importantly, walls of text on SMS kill engagement. Stride's voice must be punchy: short sentences, clear asks, no fluff.

4. **Onboarding must deliver value in week 1.** Research says first 7 days predict retention. The setup + first weekly plan must feel immediately useful.

5. **Do NOT add an app.** Not yet. SMS-only forces simplicity and preserves the engagement advantage. The moment there is an app, Stride becomes just another productivity app with a 4% day-30 retention rate.

### Risks to watch:

1. **Claude API cost spikes.** If average conversations get long, costs eat margins. The 20-turn history cap and structured check-in format are the defenses.

2. **SMS deliverability.** A2P 10DLC registration, carrier filtering, and message throughput limits are real operational concerns. Already in progress.

3. **"Just use ChatGPT" objection.** Handled by the persistence + proactive + structure combo, but messaging must be clear: "Stride remembers your patterns. ChatGPT doesn't."

4. **Noom-style billing complaints.** If Stride ever does trials-to-paid, the cancellation UX must be transparent. Noom's #1 complaint category is billing/cancellation. Do not replicate this.

---

## Sources

- [SMS vs Push Notifications (Omnisend)](https://www.omnisend.com/blog/push-notifications-vs-sms/)
- [Push Notification Statistics 2025 (MobiLoud)](https://www.mobiloud.com/blog/push-notification-statistics)
- [Motion AI Review 2026 (Rimo)](https://rimo.app/en/blogs/motion-ai_en-US)
- [Sunsama Review 2025 (Focuzed)](https://focuzed.io/blog/sunsama-review/)
- [Reclaim.ai Review (Work Management)](https://work-management.org/productivity-tools/reclaim-ai-review/)
- [Coach.me 2025 Annual Update](https://blog.coach.me/coach-me-2025-annual-update/)
- [Rocky.ai Pricing (Capterra)](https://www.capterra.com/p/10005774/Rocky/)
- [Focusmate Pricing](https://www.focusmate.com/pricing/)
- [Noom Pricing 2026](https://www.noom.com/blog/weight-management/noom-cost/)
- [Noom Behavioral Science (4-Cs)](https://www.noom.com/health/resources/blog/unlocking-lasting-change-how-nooms-4-cs-drive-better-engagement-and-outcomes/)
- [What Noom Can Teach Product Teams (Substack)](https://kristenberman.substack.com/p/what-noom-can-teach-product-teams)
- [Shine SMS Coaching Launch (TechCrunch)](https://techcrunch.com/2016/10/12/shine-is-rolling-out-on-demand-life-coaching-via-text-message/)
- [TextCoach](https://www.textcoach.com)
- [Commitment Devices vs Accountability Partners (Workmate)](https://www.workmate.com/blog/commitment-devices-vs-accountability-partners-which-works)
- [Commitment Devices Research (DarioHealth)](https://www.dariohealth.com/articles/behavioral-research-commitment-devices-tie-results-to-risk-and-reward/)
- [Data Moats (Brim Labs)](https://brimlabs.ai/blog/the-data-moat-is-the-only-moat-why-proprietary-data-pipelines-define-the-next-generation-of-ai-startups/)
- [Data and Defensibility (Abraham Thomas)](https://pivotal.substack.com/p/data-and-defensibility)
- [Freemium Conversion Rates (Userpilot)](https://userpilot.com/blog/freemium-conversion-rate/)
- [Coaching App Pricing Strategies (Passion.io)](https://passion.io/blog/effective-pricing-models-coaching-apps)
- [App Abandonment Statistics (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11694054/)
- [Mobile App Retention (Andrew Chen)](https://andrewchen.com/new-data-shows-why-losing-80-of-your-mobile-users-is-normal-and-that-the-best-apps-do-much-better/)
- [Twilio A2P 10DLC Pricing](https://help.twilio.com/articles/1260803965530-What-pricing-and-fees-are-associated-with-the-A2P-10DLC-service-)
- [Twilio SMS Pricing US](https://www.twilio.com/en-us/sms/pricing/us)
- [Motion Trustpilot Reviews](https://www.trustpilot.com/review/www.usemotion.com)
- [Todoist AI Features 2026](https://www.aitools-directory.com/tools/todoist-ai-smart-task-planning/)
- [Network Effects in SaaS](https://startupgtm.substack.com/p/network-effects-in-saas-a-desired)
- [MyFitnessPal Goal Achievement Study (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7197296/)
- [Noom Weight Maintenance Study (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10551118/)

# Stride Eval Suite

Reference for the Stride eval suite: what it covers, how to run it, and how the
levels (L1 deterministic / L2 LLM-as-judge / regression) fit together. The
original design notes and rollout plans are kept local (not committed).

---

## What you are building

A two-level eval suite in `evals/` (inside `scrumbot-app/`):

- **L1** — 12 deterministic assertions. No LLM calls. Gates every PR. Runs in `<5s`.
- **L2** — LLM-as-judge (Amazon Nova Pro via Bedrock). Marked `nightly`. Runs on cron.
- **Regression** — BUG-001 and future known bugs. Moto-based, deterministic.
- **CI** — Two GitHub Actions workflows: `evals-l1.yml` (every PR) + `evals-l2.yml` (nightly).

Methodology: Hamel Husain's eval field guide. Binary pass/fail only. Critique-then-verdict. Custom `judge.py` — no Inspect, no Braintrust.

---

## Files to create

```
scrumbot-app/                        ← you are here
├── evals/
│   ├── __init__.py
│   ├── conftest.py                  # registers pytest markers: integration, nightly
│   ├── fixtures/
│   │   ├── __init__.py
│   │   └── traces.py                # Trace dataclass + all fixture case sets
│   ├── l1/
│   │   ├── __init__.py
│   │   ├── test_assertions.py       # L1.1-L1.11 — parametrized, no LLM
│   │   └── test_classifier.py       # L1.12 — classifier recall, @pytest.mark.integration
│   ├── l2/
│   │   ├── __init__.py
│   │   ├── judge.py                 # run_judge() — critique-then-verdict via Amazon Nova Pro (Bedrock)
│   │   └── test_judges.py           # L2.1 tool selection + L2.2 coaching tone, @pytest.mark.nightly
│   └── regression/
│       ├── __init__.py
│       ├── MANIFEST.md
│       └── test_regression.py       # BUG-001 (moto-based)
├── scripts/
│   └── dump_traces.py               # Step 0: pull 100 prod traces from DynamoDB
└── pytest.ini                       # add markers block (keep testpaths = tests)

../.github/workflows/
├── evals-l1.yml                     # PR gate: L1 + regression, no LLM cost
└── evals-l2.yml                     # nightly cron: L2 judges + classifier recall

../Makefile                          # add eval-l1, eval-l2, eval-classifier targets
```

---

## Key architectural decisions (locked)

**L1 tests run against fixture data — not the live agent.** Pre-built response strings and tool_call dicts are the test inputs. $0 cost, sub-5s runtime.

**L2 tests are marked `nightly`.** They call Amazon Nova Pro via Bedrock — a different model family from the agent (`claude-sonnet-4-6`) to avoid self-preference bias. Excluded from PR CI via `-m "not nightly"`.

**L1.12 (classifier recall) is marked `integration`.** Calls Haiku (~$0.04/run). Excluded from PR CI via `-m "not integration"`. Runs in nightly CI with `ANTHROPIC_API_KEY`.

**`judge.py` uses boto3 Bedrock `converse`** (Amazon Nova Pro), not Strands and not the Anthropic SDK — a single completion call, no tools needed. Bedrock is an eval-layer carve-out from hard-constraint #3 ("never Bedrock"): evals are not production code, and the production agent + classifier stay on the Anthropic API direct.

**Regression tests reuse the moto pattern** from `tests/conftest.py` — same DynamoDB mock setup.

---

## L1 assertions reference

| ID | What it checks | Source |
|---|---|---|
| L1.1 | Response ≤ 480 chars | `shared/validators.py:44` |
| L1.2 | No scrum jargon (sprint, story, standup...) | `shared/validators.py:18-22` |
| L1.3 | No raw "XL" size label leaked to user | `shared/validators.py:25` |
| L1.4 | ≤ 1 question mark per response | `shared/validators.py:65` |
| L1.5 | Response is non-empty | `shared/validators.py:37` |
| L1.6 | Tool call inputs have all required args (all 21 tools; L1.6a anti-drift guard) | `shared/tools.py` (21 tools) |
| L1.7 | UUIDs in tool args exist in seeded fixture state | hallucinated IDs |
| L1.8 | Response contains no PII (email, phone, address) | defensive |
| L1.9 | `complete_onboarding` fires after project+cycle+task | state machine |
| L1.10 | ≤ 6 tool calls per turn | runaway loop prevention |
| L1.11 | Date fields are valid ISO + not in the past | `resolve_date` misfires |
| L1.12 | Classifier recall ≥ 0.95 per intent (40 pairs) | `shared/classifier.py` |

---

## TOOL_REQUIRED_ARGS (use this exact dict in `evals/fixtures/traces.py`)

```python
TOOL_REQUIRED_ARGS: dict[str, set[str]] = {
    "resolve_date": {"expression"},
    "create_project": {"user_id", "name"},
    "update_project": {"project_id"},
    "archive_project": {"project_id"},
    "create_work_cycle": {"project_id", "name", "start_date", "end_date"},
    "list_active_projects": set(),
    "create_task": {"title", "cycle_id"},
    "update_task_status": {"task_id", "status"},
    "get_cycle_data": {"cycle_id"},
    "create_checkin": {"user_id", "did", "doing"},
    "flag_blocker": {"task_id", "description"},
    "get_pace_history": {"project_id"},
    "get_user_patterns": {"user_id"},
    "record_velocity": {"cycle_id", "project_id", "planned_points", "delivered_points", "cycle_name"},
    "update_user_patterns": {"user_id", "delivered_points", "planned_points", "new_blockers"},
    "complete_onboarding": {"user_id"},
    "set_user_preference": {"user_id", "preference", "value"},
    "create_habit": {"user_id", "title"},
    "complete_habit": {"user_id", "habit_id"},
    "list_habits": {"user_id"},
    "submit_feedback": {"user_id", "feedback"},
}

> The required-arg sets above must stay a subset of each tool's real parameters in
> `shared/tools.py`. `evals/l1/test_assertions.py::test_l1_6a_required_args_are_real_params`
> enforces this by introspecting the live `@tool` signatures — so this table cannot
> silently drift again.
```

---

## BUG-001 regression

**Bug:** `update_user_patterns()` overwrote `preferred_tone` back to `"balanced"` even when user had explicitly set it to `"direct"` or `"encouraging"`. Fixed pre-v1.1.

**Test:**
1. Seed `PATTERN#AGGREGATE` with `preferred_tone="direct"`
2. Create project + work cycle + task (use **relative** future dates — `date.today() + timedelta(...)` — never hardcoded ISO strings)
3. Call `record_velocity()` then `update_user_patterns(user_id)`
4. Assert `preferred_tone` is still `"direct"` on the `PATTERN#AGGREGATE` record

**Use relative future dates for the work cycle** — past dates fail `create_work_cycle`
validation. Hardcoded dates (e.g. `2026-06-01`) rot into the past as the calendar moves;
both the L1.11 fixtures and the regression seeds compute dates from `date.today()` for
exactly this reason.

---

## judge.py contract

```python
def run_judge(system_prompt: str, case: dict) -> dict:
    """
    Args:
        system_prompt: rubric string with few-shot critique examples
        case: {
            "input": str,           # user message
            "response": str,        # agent response to evaluate
            # optional:
            "context": str,         # prior conversation turns
            "tool_calls": str,      # tool calls made (stringified)
            "preferred_tone": str,  # for L2.2
        }
    Returns:
        {"verdict": "pass" | "fail", "critique": str, "raw": str}
    """
```

- Model: `us.amazon.nova-pro-v1:0` (cross-region inference profile — the bare
  `amazon.nova-pro-v1:0` ID can't be invoked on-demand) via Bedrock `converse`
  (override with `BEDROCK_JUDGE_MODEL_ID`)
- Judge writes critique first, then ends with `VERDICT: PASS` or `VERDICT: FAIL`
- Verdict is read from the `VERDICT:` line; defaults to `"fail"` if absent or the
  response has no text block (fail-closed)

---

## pytest.ini — replace entire file with this

```ini
[pytest]
testpaths = tests
pythonpath = .
markers =
    integration: requires ANTHROPIC_API_KEY; skipped in PR CI
    nightly: expensive LLM calls; only runs in nightly CI
```

---

## Makefile targets to add to `../Makefile` (after existing `test:` target)

```makefile
eval-l1:
	cd scrumbot-app && .venv/bin/python -m pytest evals/l1/test_assertions.py evals/regression/ -v --tb=short -m "not integration"

eval-l2:  # Nova Pro via Bedrock — uses AWS creds from the boto3 chain, no Anthropic key
	cd scrumbot-app && .venv/bin/python -m pytest evals/l2/ -v -s -m nightly

eval-classifier:
	cd scrumbot-app && ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY) .venv/bin/python -m pytest evals/l1/test_classifier.py -v -m integration
```

---

## GitHub Actions

**`../.github/workflows/evals-l1.yml`** — runs on every PR, no LLM cost:
```yaml
name: Evals — L1 (PR gate)
on:
  pull_request:
    branches: [main]
    paths: ["scrumbot-app/**"]
jobs:
  l1-evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: cd scrumbot-app && pip install -r requirements.txt -r requirements-dev.txt
      - run: cd scrumbot-app && python -m pytest evals/l1/test_assertions.py evals/regression/ -v --tb=short -m "not integration"
      - run: cd scrumbot-app && python -m pytest tests/ -v --tb=short
```

**`../.github/workflows/evals-l2.yml`** — nightly cron. The L2 judge assumes the AWS
role via OIDC (Bedrock/Nova Pro); the classifier step keeps the Anthropic key (Haiku):
```yaml
name: Evals — L2 Nightly
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:
permissions:
  id-token: write   # OIDC for Bedrock
  contents: read
jobs:
  l2-evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: cd scrumbot-app && pip install -r requirements.txt -r requirements-dev.txt
      - run: cd scrumbot-app && python -m pytest evals/l1/test_assertions.py evals/regression/ -v -m "not integration"
      - uses: aws-actions/configure-aws-credentials@v5
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1
      - run: cd scrumbot-app && python -m pytest evals/l2/ -v -s -m nightly
      - env: { ANTHROPIC_API_KEY: "${{ secrets.ANTHROPIC_API_KEY }}" }
        run: cd scrumbot-app && python -m pytest evals/l1/test_classifier.py -v -m integration
```

---

## How to run

```bash
# L1 only (no API key needed, <5s)
make eval-l1

# L2 judges (needs AWS creds + Bedrock Nova access, calls us.amazon.nova-pro-v1:0)
make eval-l2

# Classifier recall (needs ANTHROPIC_API_KEY, calls Haiku, ~$0.04)
make eval-classifier

# Existing unit tests — must still pass after all changes
make test

# Step 0: pull prod traces for manual review before writing L2 judges
cd scrumbot-app
DYNAMODB_TABLE_NAME=stride-prod AWS_REGION=us-east-1 \
    .venv/bin/python scripts/dump_traces.py --limit 100 --out evals/fixtures/raw/
```

---

## Prod calibration runbook (closing the L2 loop)

The L2 rubrics ship as *starting points*. Before trusting Nova Pro's verdicts you must
measure its agreement with your own judgment on **real** traces — a weak judge can add
more error than the self-preference bias it removes. Run this once, then whenever the
prompt or rubrics change materially.

**Prerequisites:** AWS creds with DynamoDB read on `stride-prod` + Bedrock `InvokeModel`
on the `us.amazon.nova-pro-v1:0` inference profile **and** its underlying foundation
model `amazon.nova-pro-v1:0` (us-east-1). Bedrock model access must be enabled in the account.

1. **Pull traces** — `dump_traces.py` writes one JSON per consented user's current
   conversation to `evals/fixtures/raw/` (gitignored — real data, never commit):
   ```bash
   cd scrumbot-app
   DYNAMODB_TABLE_NAME=stride-prod AWS_REGION=us-east-1 \
       .venv/bin/python scripts/dump_traces.py --limit 100 --out evals/fixtures/raw/
   ```
2. **Hand-label ~20 cases** — read the JSON, pick ~20 (input, response, tool_calls) tuples
   spanning tool-selection and tone, and write *your own* PASS/FAIL for each. This is the
   ground truth; do it before looking at any judge output to avoid anchoring.
3. **Run the judge over the same 20** — feed them through `run_judge()` with the L2
   rubrics and record its verdict + critique.
4. **Compute agreement** — judge_verdict == your_label, as a percentage.
   - **≥ ~90%** → Nova Pro is calibrated; trust the nightly verdicts. Record the baseline
     pass-rate (how many of your 20 the agent itself passed) in this doc.
   - **< ~90%** → read the disagreements. If the *rubric* is ambiguous, tighten it and
     add the disagreeing case as a few-shot example. If Nova Pro *reasons* poorly even on
     clear cases, that's evidence to escalate to a stronger cross-family judge — and you
     now have a labeled set to pick the replacement against.
5. **Promote good cases into fixtures** — turn clear real failures into new L2 cases
   (with `expected_verdict`) and clear style failures into L1 fixtures, so each real bug
   becomes a permanent regression guard.

> `evals/fixtures/raw/` holds real user conversations — it is gitignored and must stay
> that way. Only distilled, anonymized cases move into the committed fixture files.

---

## Do not break

`make test` runs `tests/` — 261 tests, all passing. The `evals/` folder is separate; `testpaths = tests` in `pytest.ini` means it is NOT picked up by default. Confirm:

```bash
cd scrumbot-app && .venv/bin/python -m pytest --collect-only 2>&1 | grep "evals/"
# must return nothing
```

---

## Constraints (from CLAUDE.md)

- Raw Anthropic SDK is acceptable ONLY in `shared/classifier.py` (single fast completions).
  `evals/l2/judge.py` uses boto3 Bedrock (`converse`, Nova Pro) — an eval-layer carve-out
  from "never Bedrock"; see the judge.py docstring.
- No DynamoDB Scan — regression tests use `get_item` + `query` only
- Moto mock pattern: reset `shared.db._table = None` before `with mock_aws():` block
- Python 3.12 — no syntax from 3.13+
- `print()` is acceptable inside eval test files (for critique output) — not in production code

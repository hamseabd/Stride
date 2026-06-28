"""L2 LLM-as-judge evals. @nightly — calls Amazon Nova Pro via Bedrock (judge.py).

Nova Pro is a different model family from the agent under test (claude-sonnet-4-6),
chosen to avoid self-preference bias. Note: rubrics below are starting points.
Calibrate against real prod traces after running scripts/dump_traces.py and
reviewing evals/fixtures/raw/ (see EVALS.md "Prod calibration runbook").
"""
import pytest

from evals.l2.judge import run_judge

pytestmark = pytest.mark.nightly

# ---------------------------------------------------------------------------
# L2.1 — Tool selection
# ---------------------------------------------------------------------------

_TOOL_SELECTION_RUBRIC = """\
You are evaluating whether a productivity coaching AI called Stride selected the right tools for a user's request.

Evaluate the agent's tool selection based on:
1. Were the correct tools called for the user's intent?
2. Were any unnecessary tools called (wasted compute)?
3. Were any required tools skipped (incomplete action)?

Write a short critique (2-3 sentences). Then on a new line write exactly:
VERDICT: PASS
or
VERDICT: FAIL

PASS means the tool selection was correct and complete for the user's intent.
FAIL means the agent called wrong tools, skipped required tools, or called unnecessary tools.

Examples:
- User asks to add a task → agent calls create_task → VERDICT: PASS
- User asks to add a task → agent calls create_project instead → VERDICT: FAIL
- User asks to log a check-in → agent calls create_checkin + flag_blocker (no blocker mentioned) → VERDICT: FAIL
"""

_L2_1_CASES = [
    {
        "id": "correct_create_task",
        "input": "Add a task: write tests for the auth module, medium size",
        "response": "Done, I've added 'Write tests for the auth module' as a medium task to your current cycle.",
        "tool_calls": "create_task(title='Write tests for the auth module', cycle_id='...', estimate='M')",
        "expected_verdict": "pass",
    },
    {
        "id": "wrong_tool_used",
        "input": "Mark the auth task as done",
        "response": "I've updated your project.",
        "tool_calls": "update_project(project_id='...')",
        "expected_verdict": "fail",
    },
    {
        "id": "missing_complete_onboarding",
        "input": "That's my first task, what's next?",
        "response": "You're all set! Let's get to work.",
        "tool_calls": "create_project(...), create_work_cycle(...), create_task(...)",
        "context": "User just completed project, cycle, and first task creation during onboarding.",
        "expected_verdict": "fail",
    },
]


@pytest.mark.parametrize("case", _L2_1_CASES, ids=[c["id"] for c in _L2_1_CASES])
def test_l2_1_tool_selection(case):
    result = run_judge(_TOOL_SELECTION_RUBRIC, case)
    print(f"\n[{case['id']}] critique: {result['critique']}")
    assert result["verdict"] == case["expected_verdict"], (
        f"Expected {case['expected_verdict']}, got {result['verdict']}.\n{result['critique']}"
    )


# ---------------------------------------------------------------------------
# L2.2 — Coaching tone
# ---------------------------------------------------------------------------

_COACHING_TONE_RUBRIC = """\
You are evaluating whether a productivity coaching AI called Stride matched the user's preferred tone.

Tone options:
- direct: concise, no filler words, no affirmations
- encouraging: warm, affirming, celebrates progress
- balanced: neutral, supportive

Evaluate:
1. Does the response match the user's preferred_tone?
2. Is the response free of unnecessary preamble ("Great question!", "Absolutely!", "Of course!")?
3. Is it appropriately brief for SMS (aim for 1-2 sentences)?

Write a short critique (2-3 sentences). Then on a new line write exactly:
VERDICT: PASS
or
VERDICT: FAIL

PASS means tone matches the stated preference and the response is appropriately concise.
FAIL means tone mismatches the preference, or the response is padded with filler.
"""

_L2_2_CASES = [
    {
        "id": "direct_tone_match",
        "input": "What should I focus on today?",
        "response": "Your highest-priority task: finish the API integration.",
        "preferred_tone": "direct",
        "expected_verdict": "pass",
    },
    {
        "id": "direct_tone_mismatch_filler",
        "input": "What should I focus on today?",
        "response": "Great question! I'm so glad you asked. Based on everything we've discussed, I really think you should focus on your API integration today — you're doing amazing!",
        "preferred_tone": "direct",
        "expected_verdict": "fail",
    },
    {
        "id": "encouraging_tone_match",
        "input": "I finished the login flow today.",
        "response": "That's solid progress — shipping auth is never trivial. You're building momentum.",
        "preferred_tone": "encouraging",
        "expected_verdict": "pass",
    },
]


@pytest.mark.parametrize("case", _L2_2_CASES, ids=[c["id"] for c in _L2_2_CASES])
def test_l2_2_coaching_tone(case):
    result = run_judge(_COACHING_TONE_RUBRIC, case)
    print(f"\n[{case['id']}] critique: {result['critique']}")
    assert result["verdict"] == case["expected_verdict"], (
        f"Expected {case['expected_verdict']}, got {result['verdict']}.\n{result['critique']}"
    )

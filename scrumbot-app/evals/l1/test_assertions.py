"""L1 deterministic assertions. No LLM calls. Must run in <5s."""
import re
from datetime import date

import pytest

from evals.fixtures.traces import (
    BAD_ONBOARDING_EARLY,
    BAD_ONBOARDING_MISSING_TASK,
    CLEAN_RESPONSE,
    EMPTY_RESPONSE,
    GOOD_ONBOARDING_TOOL_CALLS,
    HALLUCINATED_TASK_ID,
    INVALID_DATE_CALL,
    JARGON_RESPONSE,
    LONG_RESPONSE,
    MISSING_ARG_TOOL_CALL,
    MULTI_QUESTION_RESPONSE,
    OVER_BUDGET_CALLS,
    PAST_DATE_CALL,
    PII_EMAIL_RESPONSE,
    PII_PHONE_RESPONSE,
    SEEDED_CYCLE_ID,
    SEEDED_PROJECT_ID,
    SEEDED_TASK_ID,
    TOOL_REQUIRED_ARGS,
    UNKNOWN_TOOL_CALL,
    VALID_DATE_CALL,
    VALID_RESPONSE,
    VALID_TOOL_CALL,
    WHITESPACE_RESPONSE,
    WITHIN_BUDGET_CALLS,
    XL_LABEL_RESPONSE,
)

MAX_SMS_CHARS = 480

_FORBIDDEN_TERMS = re.compile(
    r"\b(sprint|story points?|standup|stand-up|scrum|backlog|kanban|velocity|retro|retrospective)\b",
    re.IGNORECASE,
)
_SIZE_LABEL_XL = re.compile(r"\bXL\b")
_PII_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
]


# L1.1 — Response ≤ 480 chars

@pytest.mark.parametrize("trace,expected_pass", [
    (LONG_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_1_length(trace, expected_pass):
    result = len(trace.response) <= MAX_SMS_CHARS
    assert result == expected_pass, f"Length {len(trace.response)} chars"


# L1.2 — No scrum jargon

@pytest.mark.parametrize("trace,expected_pass", [
    (JARGON_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_2_jargon(trace, expected_pass):
    found = _FORBIDDEN_TERMS.findall(trace.response)
    result = len(found) == 0
    assert result == expected_pass, f"Jargon found: {found}"


# L1.3 — No raw XL size label

@pytest.mark.parametrize("trace,expected_pass", [
    (XL_LABEL_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_3_xl_label(trace, expected_pass):
    found = _SIZE_LABEL_XL.findall(trace.response)
    result = len(found) == 0
    assert result == expected_pass, f"XL found: {found}"


# L1.4 — ≤ 1 question mark per response

@pytest.mark.parametrize("trace,expected_pass", [
    (MULTI_QUESTION_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_4_single_question(trace, expected_pass):
    count = trace.response.count("?")
    result = count <= 1
    assert result == expected_pass, f"Found {count} question marks"


# L1.5 — Non-empty response

@pytest.mark.parametrize("trace,expected_pass", [
    (EMPTY_RESPONSE, False),
    (WHITESPACE_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_5_nonempty(trace, expected_pass):
    result = bool(trace.response and trace.response.strip())
    assert result == expected_pass


# L1.6 — Tool call required args present

@pytest.mark.parametrize("call,expected_pass", [
    (VALID_TOOL_CALL, True),
    (MISSING_ARG_TOOL_CALL, False),
    (UNKNOWN_TOOL_CALL, True),  # unknown tools: no required args to check
])
def test_l1_6_tool_args(call, expected_pass):
    required = TOOL_REQUIRED_ARGS.get(call["name"], set())
    present = set(call["input"].keys())
    missing = required - present
    result = len(missing) == 0
    assert result == expected_pass, f"Missing args: {missing}"


# L1.7 — Tool arg UUIDs exist in seeded fixture state (hallucination check)

SEEDED_IDS = {SEEDED_PROJECT_ID, SEEDED_CYCLE_ID, SEEDED_TASK_ID}
UUID_ARG_KEYS = {"project_id", "cycle_id", "task_id", "habit_id"}


@pytest.mark.parametrize("call,expected_pass", [
    ({"name": "get_cycle_data", "input": {"project_id": SEEDED_PROJECT_ID}}, True),
    ({"name": "update_task_status", "input": {"task_id": HALLUCINATED_TASK_ID, "status": "done"}}, False),
])
def test_l1_7_no_hallucinated_ids(call, expected_pass):
    for key, val in call["input"].items():
        if key in UUID_ARG_KEYS and val not in SEEDED_IDS:
            assert not expected_pass, f"Hallucinated ID: {key}={val}"
            return
    assert expected_pass


# L1.8 — No PII in response (email, US phone)

@pytest.mark.parametrize("trace,expected_pass", [
    (PII_EMAIL_RESPONSE, False),
    (PII_PHONE_RESPONSE, False),
    (CLEAN_RESPONSE, True),
])
def test_l1_8_no_pii(trace, expected_pass):
    for pattern in _PII_PATTERNS:
        found = pattern.findall(trace.response)
        if found:
            assert not expected_pass, f"PII found: {found}"
            return
    assert expected_pass


# L1.9 — complete_onboarding fires after project + cycle + task

def _tool_names(calls: list[dict]) -> list[str]:
    return [c["name"] for c in calls]


@pytest.mark.parametrize("calls,expected_pass", [
    (GOOD_ONBOARDING_TOOL_CALLS, True),
    (BAD_ONBOARDING_EARLY, False),
    (BAD_ONBOARDING_MISSING_TASK, False),
])
def test_l1_9_onboarding_order(calls, expected_pass):
    names = _tool_names(calls)
    if "complete_onboarding" not in names:
        assert expected_pass
        return
    co_idx = names.index("complete_onboarding")
    pre = names[:co_idx]
    ok = (
        "create_project" in pre
        and "create_work_cycle" in pre
        and "create_task" in pre
    )
    assert ok == expected_pass, f"Tool sequence: {names}"


# L1.10 — ≤ 6 tool calls per turn

@pytest.mark.parametrize("calls,expected_pass", [
    (WITHIN_BUDGET_CALLS, True),
    (OVER_BUDGET_CALLS, False),
])
def test_l1_10_tool_budget(calls, expected_pass):
    result = len(calls) <= 6
    assert result == expected_pass, f"Tool calls: {len(calls)}"


# L1.11 — Date fields are valid ISO and not in the past

_DATE_KEYS = {"start_date", "end_date", "target_date"}
_TODAY = date.today()


def _check_dates(call: dict) -> tuple[bool, str]:
    for key, val in call["input"].items():
        if key not in _DATE_KEYS:
            continue
        try:
            parsed = date.fromisoformat(val)
        except (ValueError, TypeError):
            return False, f"{key}={val!r} is not valid ISO"
        if parsed < _TODAY:
            return False, f"{key}={val} is in the past"
    return True, ""


@pytest.mark.parametrize("call,expected_pass", [
    (VALID_DATE_CALL, True),
    (PAST_DATE_CALL, False),
    (INVALID_DATE_CALL, False),
])
def test_l1_11_dates(call, expected_pass):
    ok, reason = _check_dates(call)
    assert ok == expected_pass, reason

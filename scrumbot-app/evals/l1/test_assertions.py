"""L1 deterministic assertions. No LLM calls. Must run in <5s.

Style checks (length, jargon, XL label, multiple questions, empty) delegate to the
production validator `shared.validators.validate_response` — the same code that runs
on every live reply. L1 must never re-implement these rules, or the tests would pass
while production silently drifts. Checks with no production equivalent (PII, tool
args, hallucinated IDs, onboarding order, tool budget, dates) own their own logic.
"""
import re
from datetime import date

import pytest

from shared.validators import validate_response
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

_PII_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
]


# L1.0 — Style checks must reuse the production validator, never a private copy.
# This guards against re-introducing a divergent regex: if someone redefines the
# jargon/size rules here, the eval would pass while production silently drifts.

def test_l1_0_style_checks_use_production_validator():
    import evals.l1.test_assertions as this_module
    import shared.validators as prod

    assert this_module.validate_response is prod.validate_response, (
        "L1 style checks must call shared.validators.validate_response, not a local copy"
    )
    assert not hasattr(this_module, "_FORBIDDEN_TERMS"), (
        "L1 must not define its own jargon regex — it drifts from production"
    )
    assert not hasattr(this_module, "_SIZE_LABEL_XL"), (
        "L1 must not define its own XL regex — it drifts from production"
    )


# L1.1–L1.5 delegate to the production validator so the eval and the live SMS path
# share one implementation. validate_response returns a dict of warnings;
# empty dict == clean. Each check below asserts on the specific warning key it owns.

def _warnings(trace):
    return validate_response(trace.response)


# L1.1 — Response ≤ 480 chars (production: "length_exceeded")

@pytest.mark.parametrize("trace,expected_pass", [
    (LONG_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_1_length(trace, expected_pass):
    result = "length_exceeded" not in _warnings(trace)
    assert result == expected_pass, f"Length {len(trace.response)} chars"


# L1.2 — No scrum jargon (production: "jargon")

@pytest.mark.parametrize("trace,expected_pass", [
    (JARGON_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_2_jargon(trace, expected_pass):
    warnings = _warnings(trace)
    result = "jargon" not in warnings
    assert result == expected_pass, f"Jargon found: {warnings.get('jargon')}"


# L1.3 — No raw XL size label (production: "size_labels")

@pytest.mark.parametrize("trace,expected_pass", [
    (XL_LABEL_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_3_xl_label(trace, expected_pass):
    warnings = _warnings(trace)
    result = "size_labels" not in warnings
    assert result == expected_pass, f"XL found: {warnings.get('size_labels')}"


# L1.4 — ≤ 1 question mark per response (production: "multiple_questions")

@pytest.mark.parametrize("trace,expected_pass", [
    (MULTI_QUESTION_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_4_single_question(trace, expected_pass):
    warnings = _warnings(trace)
    result = "multiple_questions" not in warnings
    assert result == expected_pass, f"Found {warnings.get('multiple_questions')} question marks"


# L1.5 — Non-empty response (production: "empty")

@pytest.mark.parametrize("trace,expected_pass", [
    (EMPTY_RESPONSE, False),
    (WHITESPACE_RESPONSE, False),
    (VALID_RESPONSE, True),
])
def test_l1_5_nonempty(trace, expected_pass):
    result = "empty" not in _warnings(trace)
    assert result == expected_pass


# L1.6 — Tool call required args present


def _call_has_all_required(call: dict) -> bool:
    """The L1.6 check: does this tool call supply every required arg?

    Single implementation of the check so test_l1_6 (hand-picked cases) and
    test_l1_6b (every tool) exercise the *same* logic — a regression here is
    caught by both, not silently passed by a tautological coverage test.
    """
    required = TOOL_REQUIRED_ARGS.get(call["name"], set())
    present = set(call["input"].keys())
    return not (required - present)


@pytest.mark.parametrize("call,expected_pass", [
    (VALID_TOOL_CALL, True),
    (MISSING_ARG_TOOL_CALL, False),
    (UNKNOWN_TOOL_CALL, True),  # unknown tools: no required args to check
])
def test_l1_6_tool_args(call, expected_pass):
    assert _call_has_all_required(call) == expected_pass


# L1.7 — Tool arg UUIDs exist in seeded fixture state (hallucination check)

SEEDED_IDS = {SEEDED_PROJECT_ID, SEEDED_CYCLE_ID, SEEDED_TASK_ID}
UUID_ARG_KEYS = {"project_id", "cycle_id", "task_id", "habit_id"}


@pytest.mark.parametrize("call,expected_pass", [
    ({"name": "get_cycle_data", "input": {"cycle_id": SEEDED_CYCLE_ID}}, True),
    ({"name": "update_task_status", "input": {"task_id": HALLUCINATED_TASK_ID, "status": "done"}}, False),
])
def test_l1_7_no_hallucinated_ids(call, expected_pass):
    for key, val in call["input"].items():
        if key in UUID_ARG_KEYS and val not in SEEDED_IDS:
            assert not expected_pass, f"Hallucinated ID: {key}={val}"
            return
    assert expected_pass


# L1.6a — Anti-drift guard: every arg named in TOOL_REQUIRED_ARGS must be a real
# parameter of the live @tool. Without this, the hand-maintained required-args dict
# silently rots away from shared/tools.py — exactly how get_cycle_data/get_pace_history/
# submit_feedback drifted (project_id/user_id/message were never real params). This is
# the L1.0-equivalent for the tool table: it makes that class of drift impossible.

def _tool_params(name: str) -> set[str]:
    import inspect
    import shared.tools as tools_module
    fn = getattr(tools_module, name)
    # Strands @tool wraps the function; the original is on __wrapped__.
    fn = getattr(fn, "__wrapped__", fn)
    return set(inspect.signature(fn).parameters)


@pytest.mark.parametrize("name", sorted(TOOL_REQUIRED_ARGS))
def test_l1_6a_required_args_are_real_params(name):
    required = TOOL_REQUIRED_ARGS[name]
    params = _tool_params(name)
    drift = required - params
    assert not drift, (
        f"TOOL_REQUIRED_ARGS['{name}'] names {drift} which are not parameters of "
        f"shared.tools.{name} (real params: {sorted(params)}). The dict has drifted "
        f"from the live signature — fix one or the other."
    )


# L1.6b — Coverage: every tool in TOOL_REQUIRED_ARGS is run through the *real* L1.6
# check (_call_has_all_required), not just the 2-3 hand-picked cases. A call with all
# required args present must pass; a call missing one required arg must fail. Iterating
# the dict means a newly added tool is covered automatically. Because these route through
# the same check as test_l1_6, a regression in that check fails here too.

def _all_present_call(name: str) -> dict:
    return {"name": name, "input": {arg: "x" for arg in TOOL_REQUIRED_ARGS[name]}}


@pytest.mark.parametrize("name", sorted(TOOL_REQUIRED_ARGS))
def test_l1_6b_all_required_present_passes(name):
    assert _call_has_all_required(_all_present_call(name)), (
        f"{name}: all required args supplied but L1.6 check reported missing"
    )


@pytest.mark.parametrize(
    "name", sorted(n for n in TOOL_REQUIRED_ARGS if TOOL_REQUIRED_ARGS[n])
)
def test_l1_6b_missing_one_required_fails(name):
    required = TOOL_REQUIRED_ARGS[name]
    dropped = sorted(required)[0]
    call = {"name": name, "input": {arg: "x" for arg in required if arg != dropped}}
    assert not _call_has_all_required(call), (
        f"{name}: dropped required arg {dropped!r} but L1.6 check still passed"
    )


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

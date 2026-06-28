"""LLM-as-judge for L2 evals.

Uses Amazon Nova Pro via AWS Bedrock (boto3 bedrock-runtime `converse`) — deliberately
a different model family from the agent under test (`claude-sonnet-4-6`) to avoid
self-preference / self-enhancement bias when Claude judges Claude.

Bedrock here is an eval-layer carve-out from repo hard-constraint #3 ("never Bedrock"):
evals are not production code, and the production agent + classifier stay on the
Anthropic API direct. Calibrate the rubrics against real prod traces (see EVALS.md
"Prod calibration runbook") before trusting verdicts — Nova Pro is a capable but weaker
judge than a top-tier model, so its agreement with human labels must be measured.
"""
import os

import boto3

# Nova Pro on Bedrock. The cross-region inference-profile ID (us. prefix) is required:
# the bare foundation-model ID `amazon.nova-pro-v1:0` only supports INFERENCE_PROFILE
# invocation, so on-demand `converse` calls against it fail with a ValidationException
# ("on-demand throughput isn't supported"). Override via BEDROCK_JUDGE_MODEL_ID.
JUDGE_MODEL_ID = os.getenv("BEDROCK_JUDGE_MODEL_ID", "us.amazon.nova-pro-v1:0")

_client = None


def _get_client():
    global _client
    if _client is None:
        # AWS_DEFAULT_REGION is the standard boto3 var; AWS_REGION is also honored.
        region = os.getenv(
            "BEDROCK_REGION",
            os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        )
        _client = boto3.client("bedrock-runtime", region_name=region)
    return _client


def run_judge(system_prompt: str, case: dict) -> dict:
    """
    Args:
        system_prompt: rubric string with few-shot critique examples
        case: {
            "input": str,           # user message
            "response": str,        # agent response to evaluate
            "context": str,         # optional: prior conversation turns
            "tool_calls": str,      # optional: tools invoked (stringified)
            "preferred_tone": str,  # optional: for L2.2 tone eval
        }
    Returns:
        {"verdict": "pass" | "fail", "critique": str, "raw": str}
    """
    user_content = f"User message: {case['input']}\n\nAgent response: {case['response']}"
    if case.get("context"):
        user_content = f"Prior context:\n{case['context']}\n\n{user_content}"
    if case.get("tool_calls"):
        user_content += f"\n\nTools called: {case['tool_calls']}"
    if case.get("preferred_tone"):
        user_content += f"\n\nUser's preferred tone: {case['preferred_tone']}"

    response = _get_client().converse(
        modelId=JUDGE_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.0},
    )

    # Fail closed if the response shape isn't the expected text block (e.g. an empty
    # content list on a guardrail/max_tokens stop, or a non-text first block). A single
    # malformed response must not crash the whole nightly run.
    try:
        blocks = response["output"]["message"]["content"]
        raw = next(b["text"] for b in blocks if "text" in b)
    except (KeyError, StopIteration, IndexError, TypeError):
        return {"verdict": "fail", "critique": "judge returned no text block", "raw": ""}

    # Derive the verdict from the dedicated VERDICT: line, not a global substring scan —
    # otherwise a critique that mentions both tokens (e.g. "almost PASS, but VERDICT: FAIL")
    # would resolve to the first one matched rather than the judge's actual verdict.
    lines = raw.strip().splitlines()
    verdict_idx = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("VERDICT:")),
        len(lines),
    )
    if verdict_idx < len(lines):
        verdict_line = lines[verdict_idx].strip().upper()
        verdict = "pass" if "PASS" in verdict_line else "fail"
    else:
        verdict = "fail"  # conservative default when no VERDICT: line is found

    critique = "\n".join(lines[:verdict_idx]).strip()

    return {"verdict": verdict, "critique": critique, "raw": raw}

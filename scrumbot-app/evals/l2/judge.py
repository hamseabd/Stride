"""LLM-as-judge for L2 evals. Raw Anthropic SDK — acceptable here (not production code)."""
import os

import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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

    message = _get_client().messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = message.content[0].text

    if "VERDICT: PASS" in raw:
        verdict = "pass"
    elif "VERDICT: FAIL" in raw:
        verdict = "fail"
    else:
        verdict = "fail"  # conservative default when neither token found

    lines = raw.strip().splitlines()
    verdict_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("VERDICT:")),
        len(lines),
    )
    critique = "\n".join(lines[:verdict_idx]).strip()

    return {"verdict": verdict, "critique": critique, "raw": raw}

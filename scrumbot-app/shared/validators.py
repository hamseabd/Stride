"""
Response validation for agent outputs.

Pure Python checks — no LLM calls, no added latency.
Logs warnings; never blocks the response from reaching the user.
"""

import re

from aws_lambda_powertools import Logger

logger = Logger(child=True)

MAX_SMS_CHARS = 480
TARGET_SMS_CHARS = 300

# Terms that must never appear in user-facing messages
_FORBIDDEN_TERMS = re.compile(
    r"\b(sprint|sprints|story|stories|standup|stand-up|fibonacci|scrumbot|"
    r"story\s*points?|velocity\s*points?|backlog\s*items?)\b",
    re.IGNORECASE,
)

# Size label leaked raw — only XL is reliably detectable (S/M/L too common in English)
_SIZE_LABEL_XL = re.compile(r"\bXL\b")


def validate_response(response: str) -> dict:
    """
    Validate an agent response before sending via SMS.

    Returns a dict of warnings (empty dict = clean response).
    Logs each warning via Powertools Logger for later analysis.
    """
    warnings = {}

    if not response or not response.strip():
        warnings["empty"] = True
        logger.error("validation_warning", check="empty_response")
        return warnings

    length = len(response)

    if length > MAX_SMS_CHARS:
        warnings["length_exceeded"] = length
        logger.warning("validation_warning", check="length_exceeded",
                       length=length, max=MAX_SMS_CHARS)

    jargon = _FORBIDDEN_TERMS.findall(response)
    if jargon:
        warnings["jargon"] = jargon
        logger.warning("validation_warning", check="jargon_detected",
                       terms=jargon, response_preview=response[:80])

    # Size labels: only flag XL (S/M/L are too common in normal English)
    xl_matches = _SIZE_LABEL_XL.findall(response)
    if xl_matches:
        warnings["size_labels"] = xl_matches
        logger.warning("validation_warning", check="size_label_exposed",
                       labels=xl_matches, response_preview=response[:80])

    # Multiple questions: warn if agent sends more than one question
    # (one question at a time is critical for SMS UX)
    question_count = response.count("?")
    if question_count > 1:
        warnings["multiple_questions"] = question_count
        logger.warning("validation_warning", check="multiple_questions",
                       count=question_count, response_preview=response[:80])

    return warnings

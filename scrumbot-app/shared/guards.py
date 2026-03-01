from aws_lambda_powertools import Logger

logger = Logger()

MAX_MESSAGE_LENGTH = 500


def check_message(message: str) -> str | None:
    """
    Validate a raw message before it reaches the agent.

    Args:
        message: Raw user message text.

    Returns:
        None       — message passes all checks.
        "empty"    — message is blank or whitespace only.
        "too_long" — message exceeds MAX_MESSAGE_LENGTH characters.
    """
    if not message or not message.strip():
        return "empty"
    if len(message) > MAX_MESSAGE_LENGTH:
        return "too_long"
    return None


def check_rate_limit(user_id: str, limit: int = 50) -> bool:
    """
    Check whether a user has exceeded their daily message limit.

    Increments the user's daily counter atomically then compares against limit.
    Fails open on DynamoDB error — a DB outage must not block legitimate users.

    Args:
        user_id: The user identifier (E.164 phone number, e.g. +14155551234).
        limit:   Maximum messages allowed per calendar day (UTC). Defaults to 50.

    Returns:
        True  — user is OVER the limit (block the message).
        False — user is at or under the limit (let the message through).
    """
    from shared.db import increment_rate_limit
    count = increment_rate_limit(user_id)
    return count > limit

import os
from urllib.parse import parse_qs

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from strands import Agent
from strands.models.anthropic import AnthropicModel

from shared.prompt import STRIDE_SYSTEM_PROMPT
from shared.guards import check_message, check_rate_limit
from shared.db import (
    log_blocked_attempt,
    get_consent, record_consent, revoke_consent,
    get_or_create_user,
)
from shared.tools import (
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
)

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()

SMS_MAX_CHARS = 1600   # Twilio hard limit
SMS_TARGET_CHARS = 300 # soft target — keep responses short

TOOLS = [
    create_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
]

_OPT_IN_PROMPT = (
    "Welcome to Stride — a personal productivity coach.\n"
    "Reply YES to receive daily check-in reminders.\n"
    "Reply STOP anytime to unsubscribe."
)
_WELCOME = (
    "You're in! I'm Stride, your productivity coach.\n"
    "Tell me what you're working on and I'll help you plan your week."
)
_UNSUBSCRIBED = (
    "You've been unsubscribed from Stride. "
    "Text us again anytime to re-join."
)
_HELP_TEXT = (
    "Stride helps you plan your week, check in daily, and review progress.\n"
    "Just text me naturally — e.g. 'plan my week' or 'I finished the logo'.\n"
    "Reply STOP to unsubscribe."
)
_BLOCKED_REPLY = (
    "I'm Stride — I only help with your goals and plans.\n"
    "Want to set a goal, check in on progress, or review your week?"
)
_ERROR_REPLY = "Something went wrong. Try again in a moment."

_SMS_SYSTEM_ADDENDUM = """
You are responding via SMS. Additional rules:
- Keep every reply under 300 characters when possible.
- Never use markdown, bullet points, or any formatting.
- Plain sentences only. If you need more space, send the most important part
  and ask if they want more detail.
- Never expose internal IDs, error messages, or technical details.
"""

_ONBOARDING_ADDENDUM = """
This is a new user — they have no projects yet.
Start with setup: ask what they are working on.
Once they tell you, create their first project, first work cycle covering
this week, and their initial tasks. After creating at least one task,
call complete_onboarding to mark them as set up.
"""


def _validate_twilio(event: dict) -> bool:
    """Validate that the request genuinely came from Twilio."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not set — skipping signature validation")
        return True

    validator = RequestValidator(auth_token)
    signature = event.get("headers", {}).get("X-Twilio-Signature", "")
    url = (
        "https://"
        + event.get("requestContext", {}).get("domainName", "")
        + event.get("rawPath", "/sms")
    )
    params = {
        k: v[0] if isinstance(v, list) else v
        for k, v in parse_qs(event.get("body", "")).items()
    }
    return validator.validate(url, params, signature)


def _twiml(text: str) -> dict:
    """Wrap text in a TwiML HTTP response, truncating at SMS_MAX_CHARS."""
    if len(text) > SMS_MAX_CHARS:
        # Truncate at last sentence boundary before the limit
        truncated = text[:SMS_MAX_CHARS]
        last_period = max(
            truncated.rfind(". "),
            truncated.rfind(".\n"),
            truncated.rfind("? "),
            truncated.rfind("! "),
        )
        text = truncated[: last_period + 1] if last_period > 0 else truncated
    response = MessagingResponse()
    response.message(text)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/xml"},
        "body": str(response),
    }


def _call_agent(user_id: str, message: str, is_new_user: bool) -> str:
    """Run the Stride agent for an SMS message. Returns the reply string."""
    system = (
        STRIDE_SYSTEM_PROMPT.strip()
        + f"\n\nCurrent user_id: {user_id}"
        + _SMS_SYSTEM_ADDENDUM
    )
    if is_new_user:
        system += _ONBOARDING_ADDENDUM

    model = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=512)
    agent = Agent(model=model, system_prompt=system, tools=TOOLS, messages=[])
    result = agent(message)
    return str(result)


@app.post("/sms")
def sms():
    """
    POST /sms — Twilio SMS webhook (form-encoded).

    Guard chain:
      1. Twilio signature validation
      2. Parse user_id (From) + message (Body)
      3. Message length / empty check
      4. Per-user daily rate limit (50 msgs/day)
      5. STOP keyword  → revoke consent
      6. HELP keyword  → help text
      7. Consent check → opt-in prompt or record YES
      8. User bootstrap (get or create USER# record)
      9. Onboarding detection
     10. Stride agent
    """
    event = app.current_event._data  # raw API GW event

    # 1. Twilio signature validation
    if not _validate_twilio(event):
        logger.warning("Invalid Twilio signature")
        return {"statusCode": 403, "body": "Forbidden"}

    # 2. Parse fields
    body    = parse_qs(event.get("body", ""))
    user_id = body.get("From", ["unknown"])[0]
    message = body.get("Body", [""])[0].strip()

    logger.info("SMS received", user_id=user_id)

    # 3. Message validation
    msg_check = check_message(message)
    if msg_check is not None:
        logger.info("Message blocked", user_id=user_id, reason=msg_check)
        log_blocked_attempt(user_id, msg_check, message)
        return _twiml(_BLOCKED_REPLY)

    # 4. Rate limit
    if check_rate_limit(user_id):
        logger.info("Rate limit exceeded", user_id=user_id)
        log_blocked_attempt(user_id, "rate_limit", message)
        return _twiml(_BLOCKED_REPLY)

    msg_upper = message.upper().strip()

    # 5. STOP keyword — revoke consent immediately
    if msg_upper == "STOP":
        revoke_consent(user_id)
        logger.info("User unsubscribed", user_id=user_id)
        return _twiml(_UNSUBSCRIBED)

    # 6. HELP keyword
    if msg_upper == "HELP":
        return _twiml(_HELP_TEXT)

    # 7. Consent check
    consent = get_consent(user_id)
    consent_active = consent is not None and consent.get("status") == "active"

    if not consent_active:
        if msg_upper == "YES":
            record_consent(user_id=user_id, phone=user_id)
            # Fall through to user bootstrap + agent
        else:
            # No consent yet — send opt-in prompt
            logger.info("Sending opt-in prompt", user_id=user_id)
            return _twiml(_OPT_IN_PROMPT)

    # 8. User bootstrap
    user = get_or_create_user(user_id=user_id, phone=user_id)
    if "error" in user:
        logger.error("get_or_create_user failed", user_id=user_id, error=user["error"])
        return _twiml(_ERROR_REPLY)

    # Send welcome on first YES before hitting agent
    if msg_upper == "YES" and not consent_active:
        logger.info("New user welcomed", user_id=user_id)
        return _twiml(_WELCOME)

    # 9. Onboarding detection
    is_new_user = not user.get("onboarded", False)
    if is_new_user:
        projects = list_active_projects(user_id=user_id)
        # If they already have projects (e.g. created via /ceremony), mark as onboarded
        if projects.get("projects"):
            is_new_user = False

    logger.info("Routing to agent", user_id=user_id, is_new_user=is_new_user)

    # 10. Stride agent
    try:
        reply = _call_agent(user_id=user_id, message=message, is_new_user=is_new_user)
        return _twiml(reply)
    except Exception as e:
        logger.exception("SMS agent call failed", user_id=user_id)
        return _twiml(_ERROR_REPLY)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)

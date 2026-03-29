import os

from aws_lambda_powertools import Logger
from twilio.rest import Client

logger = Logger()

_client = None


MAX_OUTBOUND_CHARS = 480  # 3 SMS segments — hard cap on outbound messages


def _get_client() -> Client:
    """Lazy-init Twilio REST client."""
    global _client
    if _client is None:
        sid = os.environ.get("TWILIO_ACCOUNT_SID")
        token = os.environ.get("TWILIO_AUTH_TOKEN")
        if not sid or not token:
            raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
        _client = Client(sid, token)
    return _client


def send_sms(to: str, body: str) -> bool:
    """
    Send an outbound SMS via Twilio.

    Args:
        to:   Recipient phone number in E.164 format (e.g. +15551234567).
        body: Message text. Truncated to MAX_OUTBOUND_CHARS if too long.

    Returns:
        True on success, False on error (logged, never raised).
    """
    if len(body) > MAX_OUTBOUND_CHARS:
        body = body[:MAX_OUTBOUND_CHARS - 3] + "..."
    from_number = os.environ.get("TWILIO_PHONE_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_PHONE_NUMBER not set")
        return False
    try:
        msg = _get_client().messages.create(to=to, from_=from_number, body=body)
        logger.info("SMS sent", to=to, sid=msg.sid)
        return True
    except Exception as e:
        logger.error("send_sms failed", to=to, error=str(e))
        return False

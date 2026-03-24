import os

from aws_lambda_powertools import Logger
from twilio.rest import Client

logger = Logger()

_client = None


def _get_client() -> Client:
    """Lazy-init Twilio REST client."""
    global _client
    if _client is None:
        sid = os.environ["TWILIO_ACCOUNT_SID"]
        token = os.environ["TWILIO_AUTH_TOKEN"]
        _client = Client(sid, token)
    return _client


def send_sms(to: str, body: str) -> bool:
    """
    Send an outbound SMS via Twilio.

    Args:
        to:   Recipient phone number in E.164 format (e.g. +15551234567).
        body: Message text. Caller is responsible for length limits.

    Returns:
        True on success, False on error (logged, never raised).
    """
    from_number = os.environ["TWILIO_PHONE_NUMBER"]
    try:
        msg = _get_client().messages.create(to=to, from_=from_number, body=body)
        logger.info("SMS sent", to=to, sid=msg.sid)
        return True
    except Exception as e:
        logger.error("send_sms failed", to=to, error=str(e))
        return False

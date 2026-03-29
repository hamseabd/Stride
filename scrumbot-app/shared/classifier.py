"""
Intent classifier using Claude Haiku.

Classifies inbound SMS messages into one of:
  feedback, remind_me, no_reminders, help, conversation

Uses raw Anthropic SDK (not Strands) — no tools needed, just a single fast completion.
Cost: ~$0.001 per classification (50 input tokens, 1 output token).
"""

import os
import time

import anthropic
from aws_lambda_powertools import Logger

logger = Logger()

VALID_INTENTS = {"feedback", "remind_me", "no_reminders", "help", "conversation"}

_CLASSIFIER_PROMPT = """Classify this SMS message into exactly one intent.

Intents:
- feedback: user is giving feedback about this product itself — complaints, suggestions, praise, "this isn't helpful", "you should do X", "I like how you..."
- remind_me: user wants to opt in to daily proactive reminders — "remind me", "sure remind me", "yes", "ok" (ONLY when it clearly means opting into reminders, not asking to be reminded about a task)
- no_reminders: user wants to stop daily reminders — "no reminders", "stop reminders", "no more reminders"
- help: user asking what this product does, how to use it, or what commands are available — "help", "what can you do", "how does this work"
- conversation: anything else — talking about goals, tasks, plans, check-ins, updates, questions about their work

Message: "{message}"

Reply with exactly one word: feedback, remind_me, no_reminders, help, or conversation"""

_client = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-init Anthropic client."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def classify_intent(message: str) -> str:
    """
    Classify user message intent using Claude Haiku.

    Args:
        message: Raw SMS message text.

    Returns:
        One of: "feedback", "remind_me", "no_reminders", "help", "conversation"
        Returns "conversation" on any error (fail open to Sonnet agent).
    """
    try:
        prompt = _CLASSIFIER_PROMPT.replace("{message}", message)
        t0 = time.monotonic()
        resp = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        classifier_ms = round((time.monotonic() - t0) * 1000)
        intent = resp.content[0].text.strip().lower()

        if intent not in VALID_INTENTS:
            logger.warning("Classifier returned unknown intent", intent=intent, user_message=message[:50])
            return "conversation"

        usage = resp.usage
        logger.info("classifier_metrics",
                     intent=intent,
                     classifier_latency_ms=classifier_ms,
                     input_tokens=usage.input_tokens,
                     output_tokens=usage.output_tokens,
                     user_message=message[:50])
        return intent

    except Exception as e:
        logger.error("Classifier failed — falling back to conversation", error=str(e))
        return "conversation"

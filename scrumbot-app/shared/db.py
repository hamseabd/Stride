import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import boto3
from aws_lambda_powertools import Logger

from shared.models import User

logger = Logger()


def get_table():
    """Return boto3 Table resource for the configured DynamoDB table."""
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "stride-local")
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    kwargs = {"endpoint_url": endpoint} if endpoint else {}
    return boto3.resource("dynamodb", region_name="us-east-1", **kwargs).Table(table_name)


def increment_rate_limit(user_id: str) -> int:
    """
    Atomically increment the daily message counter for a user and return the new count.

    DynamoDB key:
        PK: USER#{user_id}
        SK: RATELIMIT#{YYYY-MM-DD}   (today's UTC date)

    Args:
        user_id: The user identifier (E.164 phone number, e.g. +14155551234).

    Returns:
        The new message count after increment.
        Returns 0 on any DynamoDB error (fail open — a DB outage must not
        block legitimate users).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        resp = get_table().update_item(
            Key={
                "pk": f"USER#{user_id}",
                "sk": f"RATELIMIT#{today}",
            },
            UpdateExpression=(
                "ADD message_count :one "
                "SET created_at = if_not_exists(created_at, :now)"
            ),
            ExpressionAttributeValues={":one": 1, ":now": now},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"].get("message_count", 0))
    except Exception as e:
        logger.error(
            "increment_rate_limit failed — failing open",
            error=str(e),
            user_id=user_id,
        )
        return 0


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def get_consent(user_id: str) -> dict | None:
    """
    Return the CONSENT#SMS record for a user, or None if not found.
    Returns None on error (fail open — a DB outage must not block users).
    """
    try:
        resp = get_table().get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONSENT#SMS"}
        )
        return resp.get("Item")
    except Exception as e:
        logger.error("get_consent failed — failing open", error=str(e), user_id=user_id)
        return None


def record_consent(user_id: str, phone: str) -> bool:
    """
    Write USER#{user_id} / CONSENT#SMS with consented_at and status="active".
    Returns True on success, False on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": "CONSENT#SMS",
            "phone": phone,
            "status": "active",
            "consented_at": now,
            "created_at": now,
        })
        logger.info("Consent recorded", user_id=user_id)
        return True
    except Exception as e:
        logger.error("record_consent failed", error=str(e), user_id=user_id)
        return False


def revoke_consent(user_id: str) -> bool:
    """
    Set status="revoked" on the CONSENT#SMS record.
    Returns True on success, False on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().update_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONSENT#SMS"},
            UpdateExpression="SET #s = :revoked, revoked_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":revoked": "revoked", ":now": now},
        )
        logger.info("Consent revoked", user_id=user_id)
        return True
    except Exception as e:
        logger.error("revoke_consent failed", error=str(e), user_id=user_id)
        return False


# ---------------------------------------------------------------------------
# Proactive consent (TCPA — separate from inbound SMS consent)
# ---------------------------------------------------------------------------

def get_proactive_consent(user_id: str) -> dict | None:
    """
    Return the CONSENT#PROACTIVE record for a user, or None if not found.
    Returns None on error (fail open).
    """
    try:
        resp = get_table().get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONSENT#PROACTIVE"}
        )
        return resp.get("Item")
    except Exception as e:
        logger.error("get_proactive_consent failed", error=str(e), user_id=user_id)
        return None


def record_proactive_consent(user_id: str) -> bool:
    """
    Write CONSENT#PROACTIVE with status=active and GSI keys for scheduler lookup.
    GSI1: gsi1pk="PROACTIVE#ACTIVE", gsi1sk="USER#{user_id}"
    Returns True on success, False on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": "CONSENT#PROACTIVE",
            "status": "active",
            "gsi1pk": "PROACTIVE#ACTIVE",
            "gsi1sk": f"USER#{user_id}",
            "consented_at": now,
            "created_at": now,
        })
        logger.info("Proactive consent recorded", user_id=user_id)
        return True
    except Exception as e:
        logger.error("record_proactive_consent failed", error=str(e), user_id=user_id)
        return False


def revoke_proactive_consent(user_id: str) -> bool:
    """
    Set status=revoked on CONSENT#PROACTIVE and remove GSI keys.
    Returns True on success, False on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().update_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONSENT#PROACTIVE"},
            UpdateExpression="SET #s = :revoked, revoked_at = :now REMOVE gsi1pk, gsi1sk",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":revoked": "revoked", ":now": now},
        )
        logger.info("Proactive consent revoked", user_id=user_id)
        return True
    except Exception as e:
        logger.error("revoke_proactive_consent failed", error=str(e), user_id=user_id)
        return False


def get_consented_users() -> list[str]:
    """
    Query GSI for all users with active proactive consent.
    Returns list of user_id strings (e.g. ["+15551234567", ...]).
    Returns empty list on error (fail open).
    """
    try:
        from boto3.dynamodb.conditions import Key
        resp = get_table().query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq("PROACTIVE#ACTIVE"),
        )
        items = resp.get("Items", [])
        # Extract user_id from pk: "USER#+15551234567" → "+15551234567"
        return [item["pk"].removeprefix("USER#") for item in items]
    except Exception as e:
        logger.error("get_consented_users failed", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Outbound message logging
# ---------------------------------------------------------------------------

def log_outbound(user_id: str, body: str, message_type: str) -> str | None:
    """
    Log an outbound proactive message.
    DynamoDB: USER#{user_id} / OUTBOUND#{iso_timestamp}
    Returns the SK on success (for replied_at tracking), None on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    sk = f"OUTBOUND#{now}"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": sk,
            "body": body,
            "message_type": message_type,
            "sent_at": now,
        })
        logger.info("Outbound logged", user_id=user_id, message_type=message_type)
        return sk
    except Exception as e:
        logger.error("log_outbound failed", error=str(e), user_id=user_id)
        return None


def get_latest_outbound(user_id: str) -> dict | None:
    """
    Get the most recent OUTBOUND# record for a user.
    Returns the item dict or None.
    """
    try:
        from boto3.dynamodb.conditions import Key
        resp = get_table().query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("OUTBOUND#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.error("get_latest_outbound failed", error=str(e), user_id=user_id)
        return None


def set_outbound_replied(user_id: str, outbound_sk: str) -> bool:
    """
    Set replied_at on an outbound record (for tone derivation latency tracking).
    Returns True on success, False on error.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().update_item(
            Key={"pk": f"USER#{user_id}", "sk": outbound_sk},
            UpdateExpression="SET replied_at = :now",
            ExpressionAttributeValues={":now": now},
        )
        return True
    except Exception as e:
        logger.error("set_outbound_replied failed", error=str(e), user_id=user_id)
        return False


def get_todays_outbound(user_id: str, date_str: str) -> list[dict]:
    """
    Get all outbound records for a user on a given date (for deduplication).
    date_str: "YYYY-MM-DD" in user's local timezone.
    Returns list of outbound items, empty list on error.
    """
    try:
        from boto3.dynamodb.conditions import Key
        resp = get_table().query(
            KeyConditionExpression=(
                Key("pk").eq(f"USER#{user_id}")
                & Key("sk").begins_with(f"OUTBOUND#{date_str}")
            ),
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error("get_todays_outbound failed", error=str(e), user_id=user_id)
        return []


def get_outbound_since(user_id: str, since_date: str) -> list[dict]:
    """
    Get all outbound records for a user since a given date (inclusive).
    since_date: "YYYY-MM-DD"
    Returns list of outbound items, empty list on error.
    """
    try:
        from boto3.dynamodb.conditions import Key
        resp = get_table().query(
            KeyConditionExpression=(
                Key("pk").eq(f"USER#{user_id}")
                & Key("sk").between(f"OUTBOUND#{since_date}", "OUTBOUND#9999")
            ),
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error("get_outbound_since failed", error=str(e), user_id=user_id)
        return []


def update_preferred_tone(user_id: str, tone: str) -> bool:
    """
    Update preferred_tone on the PATTERN#AGGREGATE record.
    tone: "direct" | "encouraging" | "balanced"
    Returns True on success, False on error.
    """
    try:
        get_table().update_item(
            Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"},
            UpdateExpression="SET preferred_tone = :tone",
            ExpressionAttributeValues={":tone": tone},
        )
        logger.info("Preferred tone updated", user_id=user_id, tone=tone)
        return True
    except Exception as e:
        logger.error("update_preferred_tone failed", error=str(e), user_id=user_id)
        return False


# ---------------------------------------------------------------------------
# User bootstrap
# ---------------------------------------------------------------------------

def get_or_create_user(user_id: str, phone: str) -> dict:
    """
    Return the USER#{user_id}/#METADATA record. Creates it if it does not exist.
    Returns the user dict on success, {"error": str} on failure.
    """
    try:
        table = get_table()
        resp  = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "#METADATA"})
        item  = resp.get("Item")
        if item:
            return item

        user = User(user_id=user_id, phone=phone)
        new_item = user.model_dump()
        new_item["pk"] = f"USER#{user_id}"
        new_item["sk"] = "#METADATA"
        table.put_item(Item=new_item, ConditionExpression="attribute_not_exists(pk)")
        logger.info("User created", user_id=user_id)
        return new_item
    except Exception as e:
        # ConditionalCheckFailedException means another request created the user
        # simultaneously — fetch and return the existing record.
        if "ConditionalCheckFailedException" in type(e).__name__:
            try:
                resp = get_table().get_item(Key={"pk": f"USER#{user_id}", "sk": "#METADATA"})
                return resp.get("Item", {"error": "user not found after race"})
            except Exception as e2:
                logger.error("get_or_create_user race recovery failed", error=str(e2))
                return {"error": str(e2)}
        logger.error("get_or_create_user failed", error=str(e), user_id=user_id)
        return {"error": str(e)}


def set_onboarded(user_id: str) -> bool:
    """
    Mark a user as onboarded (sets onboarded=True on USER#{user_id}/#METADATA).
    Returns True on success, False on error.
    """
    try:
        get_table().update_item(
            Key={"pk": f"USER#{user_id}", "sk": "#METADATA"},
            UpdateExpression="SET onboarded = :t",
            ExpressionAttributeValues={":t": True},
        )
        logger.info("User marked as onboarded", user_id=user_id)
        return True
    except Exception as e:
        logger.error("set_onboarded failed", error=str(e), user_id=user_id)
        return False


def log_blocked_attempt(user_id: str, reason: str, message_preview: str) -> None:
    """
    Log a blocked message attempt to DynamoDB.

    DynamoDB key:
        PK: USER#{user_id}
        SK: BLOCKED#{iso_timestamp}

    Attributes: reason, message_preview (first 100 chars only), created_at.
    Atomic put_item — no read before write.
    Errors are logged and swallowed — a logging failure must not surface to the user.

    Args:
        user_id:         The user identifier.
        reason:          Why the message was blocked ("empty", "too_long", "rate_limit").
        message_preview: The raw message — only the first 100 chars are stored.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": f"BLOCKED#{now}",
            "reason": reason,
            "message_preview": message_preview[:100],
            "created_at": now,
        })
    except Exception as e:
        logger.error(
            "log_blocked_attempt failed",
            error=str(e),
            user_id=user_id,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

def get_conversation(user_id: str) -> list:
    """
    Load the current conversation history for a user.
    Returns the stored messages list, or empty list if none exists.

    Weekly reset: if today is the user's planning day and we haven't
    reset yet today, clear the history (fresh start for the week).

    Returns empty list on error (fail open).
    """
    try:
        resp = get_table().get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"}
        )
        item = resp.get("Item")
        if not item:
            return []

        planning_day = int(item.get("planning_day", 1))
        user_tz_str = item.get("user_timezone", "America/New_York")
        try:
            user_tz = ZoneInfo(user_tz_str)
        except Exception:
            user_tz = ZoneInfo("America/New_York")

        last_reset = item.get("last_reset_date", "")
        now_local = datetime.now(user_tz)
        today = now_local.strftime("%Y-%m-%d")
        weekday = now_local.isoweekday()  # 1=Monday, 7=Sunday

        if weekday == planning_day and last_reset != today:
            logger.info("Weekly conversation reset", user_id=user_id)
            get_table().update_item(
                Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"},
                UpdateExpression="SET messages = :empty, last_reset_date = :today",
                ExpressionAttributeValues={":empty": "[]", ":today": today},
            )
            return []

        messages_json = item.get("messages", "[]")
        loaded = json.loads(messages_json) if isinstance(messages_json, str) else messages_json

        # Validate: strip any orphaned tool_result messages at the start
        # (tool_result without a preceding assistant tool_use causes API 400)
        tool_result_types = {"toolResult", "tool_result"}
        validated = []
        for msg in loaded:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", [])
            if role == "user" and isinstance(content, list) and all(
                isinstance(c, dict) and c.get("type") in tool_result_types for c in content
            ):
                continue  # drop orphaned tool_result messages
            validated.append(msg)
        return validated
    except Exception as e:
        logger.error("get_conversation failed — returning empty", error=str(e), user_id=user_id)
        return []


def save_conversation(user_id: str, messages: list, planning_day: int = 1, user_timezone: str = "America/New_York") -> bool:
    """
    Write updated conversation history, capped at 20 turns.
    Strips tool call/result payloads to stay under DynamoDB's 400KB item limit.
    Includes byte-size safety check — trims further if JSON exceeds 350KB.

    Returns True on success, False on error.
    """
    try:
        tool_types_result = {"toolResult", "tool_result"}
        tool_types_use = {"toolUse", "tool_use"}

        stripped = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                if role == "user":
                    content = msg.get("content", [])
                    if isinstance(content, list) and all(
                        isinstance(c, dict) and c.get("type") in tool_types_result for c in content
                    ):
                        continue
                    stripped.append(msg)
                elif role == "assistant":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        text_only = [c for c in content if not (isinstance(c, dict) and c.get("type") in tool_types_use)]
                        if text_only:
                            stripped.append({"role": "assistant", "content": text_only})
                    elif isinstance(content, str):
                        stripped.append(msg)

        if len(stripped) > 20:
            stripped = stripped[-20:]

        messages_json = json.dumps(stripped)
        while len(messages_json.encode("utf-8")) > 350_000 and len(stripped) > 2:
            stripped = stripped[2:]
            messages_json = json.dumps(stripped)

        now = datetime.now(timezone.utc).isoformat() + "Z"
        try:
            user_tz = ZoneInfo(user_timezone)
        except Exception:
            user_tz = ZoneInfo("America/New_York")
        now_local = datetime.now(user_tz)
        today = now_local.strftime("%Y-%m-%d")

        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": "CONVERSATION#CURRENT",
            "messages": messages_json,
            "turn_count": len(stripped),
            "planning_day": planning_day,
            "user_timezone": user_timezone,
            "last_reset_date": today if now_local.isoweekday() == planning_day else "",
            "updated_at": now,
        })
        return True
    except Exception as e:
        logger.error("save_conversation failed", error=str(e), user_id=user_id)
        return False


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def store_feedback(user_id: str, text: str, source: str) -> None:
    """
    Persist user feedback to DynamoDB.

    DynamoDB key:
        PK: USER#{user_id}
        SK: FEEDBACK#{iso_timestamp}

    source: "keyword" (user typed FEEDBACK ...) | "agent" (agent-prompted after review)
    Errors are swallowed — a logging failure must not surface to the user.
    """
    now = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": f"FEEDBACK#{now}",
            "body": text,
            "source": source,
            "created_at": now,
        })
        logger.info("Feedback stored", user_id=user_id, source=source)
    except Exception as e:
        logger.error("store_feedback failed", error=str(e), user_id=user_id)

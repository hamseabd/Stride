import os
from datetime import datetime, timezone

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
        user_id: The user identifier (WhatsApp WaId).

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

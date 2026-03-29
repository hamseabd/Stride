"""Tests for Phase 3 — proactive consent, outbound logging, and scheduler logic."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from shared.db import (
    get_proactive_consent,
    record_proactive_consent,
    revoke_proactive_consent,
    get_consented_users,
    log_outbound,
    get_latest_outbound,
    set_outbound_replied,
    get_todays_outbound,
    get_outbound_since,
    update_preferred_tone,
    get_table,
)


# ── Proactive consent ────────────────────────────────────────────────────────


class TestProactiveConsent:
    def test_no_consent_returns_none(self, ddb, user_id):
        assert get_proactive_consent(user_id) is None

    def test_record_and_get(self, ddb, user_id):
        assert record_proactive_consent(user_id) is True
        consent = get_proactive_consent(user_id)
        assert consent is not None
        assert consent["status"] == "active"
        assert consent["gsi1pk"] == "PROACTIVE#ACTIVE"
        assert consent["gsi1sk"] == f"USER#{user_id}"

    def test_revoke(self, ddb, user_id):
        record_proactive_consent(user_id)
        assert revoke_proactive_consent(user_id) is True
        consent = get_proactive_consent(user_id)
        assert consent["status"] == "revoked"
        assert "gsi1pk" not in consent
        assert "gsi1sk" not in consent

    def test_revoke_nonexistent_is_safe(self, ddb, user_id):
        # revoke_proactive_consent on a user with no record — should not crash
        # DynamoDB update_item creates the item if it doesn't exist
        result = revoke_proactive_consent(user_id)
        assert result is True


class TestConsentedUsers:
    def test_empty_when_none(self, ddb):
        assert get_consented_users() == []

    def test_returns_active_users(self, ddb):
        record_proactive_consent("+15551111111")
        record_proactive_consent("+15552222222")
        users = get_consented_users()
        assert set(users) == {"+15551111111", "+15552222222"}

    def test_excludes_revoked(self, ddb):
        record_proactive_consent("+15551111111")
        record_proactive_consent("+15552222222")
        revoke_proactive_consent("+15552222222")
        users = get_consented_users()
        assert users == ["+15551111111"]


# ── Outbound logging ─────────────────────────────────────────────────────────


class TestOutboundLogging:
    def test_log_outbound(self, ddb, user_id):
        sk = log_outbound(user_id, "Good morning!", "morning_reminder")
        assert sk is not None
        assert sk.startswith("OUTBOUND#")

    def test_get_latest_outbound(self, ddb, user_id):
        sk = log_outbound(user_id, "Only message", "morning_reminder")
        latest = get_latest_outbound(user_id)
        assert latest is not None
        assert latest["body"] == "Only message"
        assert latest["message_type"] == "morning_reminder"
        assert latest["sk"] == sk

    def test_get_latest_outbound_empty(self, ddb, user_id):
        assert get_latest_outbound(user_id) is None

    def test_set_outbound_replied(self, ddb, user_id):
        sk = log_outbound(user_id, "Hello", "morning_reminder")
        assert set_outbound_replied(user_id, sk) is True
        latest = get_latest_outbound(user_id)
        assert "replied_at" in latest

    def test_get_todays_outbound(self, ddb, user_id):
        log_outbound(user_id, "Morning msg", "morning_reminder")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items = get_todays_outbound(user_id, today)
        assert len(items) == 1
        assert items[0]["message_type"] == "morning_reminder"

    def test_get_todays_outbound_wrong_date(self, ddb, user_id):
        log_outbound(user_id, "Morning msg", "morning_reminder")
        items = get_todays_outbound(user_id, "1999-01-01")
        assert len(items) == 0

    def test_get_outbound_since(self, ddb, user_id):
        log_outbound(user_id, "Old msg", "morning_reminder")
        log_outbound(user_id, "New msg", "evening_checkin")
        items = get_outbound_since(user_id, "2020-01-01")
        assert len(items) == 2

    def test_get_outbound_since_future_date(self, ddb, user_id):
        log_outbound(user_id, "A msg", "morning_reminder")
        items = get_outbound_since(user_id, "2099-01-01")
        assert len(items) == 0


# ── Preferred tone ────────────────────────────────────────────────────────────


class TestPreferredTone:
    def test_update_preferred_tone(self, ddb, user_id):
        # Create the pattern record first
        get_table().put_item(Item={
            "pk": f"USER#{user_id}",
            "sk": "PATTERN#AGGREGATE",
            "preferred_tone": "balanced",
        })
        assert update_preferred_tone(user_id, "direct") is True
        resp = get_table().get_item(
            Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"}
        )
        assert resp["Item"]["preferred_tone"] == "direct"

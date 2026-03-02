from shared.db import (
    get_table, increment_rate_limit,
    get_consent, record_consent, revoke_consent,
    get_or_create_user, set_onboarded, log_blocked_attempt,
)


class TestRateLimit:
    def test_increment(self, ddb, user_id):
        count = increment_rate_limit(user_id)
        assert count == 1

    def test_increment_twice(self, ddb, user_id):
        increment_rate_limit(user_id)
        count = increment_rate_limit(user_id)
        assert count == 2


class TestConsent:
    def test_no_consent_returns_none(self, ddb, user_id):
        assert get_consent(user_id) is None

    def test_record_and_get(self, ddb, user_id):
        assert record_consent(user_id=user_id, phone=user_id) is True
        consent = get_consent(user_id)
        assert consent is not None
        assert consent["status"] == "active"

    def test_revoke(self, ddb, user_id):
        record_consent(user_id=user_id, phone=user_id)
        assert revoke_consent(user_id) is True
        consent = get_consent(user_id)
        assert consent["status"] == "revoked"


class TestUserBootstrap:
    def test_create_new_user(self, ddb, user_id):
        user = get_or_create_user(user_id=user_id, phone=user_id)
        assert user["user_id"] == user_id
        assert user["phone"] == user_id
        assert user.get("onboarded") is False

    def test_get_existing_user(self, ddb, user_id):
        get_or_create_user(user_id=user_id, phone=user_id)
        user = get_or_create_user(user_id=user_id, phone=user_id)
        assert user["user_id"] == user_id

    def test_set_onboarded(self, ddb, user_id):
        get_or_create_user(user_id=user_id, phone=user_id)
        assert set_onboarded(user_id) is True
        user = get_or_create_user(user_id=user_id, phone=user_id)
        assert user["onboarded"] is True

    def test_new_user_has_preference_defaults(self, ddb, user_id):
        user = get_or_create_user(user_id=user_id, phone=user_id)
        assert user.get("timezone") == "America/New_York"
        assert user.get("checkin_time") == "09:00"
        assert user.get("planning_day") == 1


class TestBlockedLog:
    def test_log_blocked(self, ddb, user_id):
        log_blocked_attempt(user_id, "too_long", "a" * 200)
        table = get_table()
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":sk": "BLOCKED#",
            },
        )
        items = resp["Items"]
        assert len(items) == 1
        assert items[0]["reason"] == "too_long"
        assert len(items[0]["message_preview"]) == 100  # truncated

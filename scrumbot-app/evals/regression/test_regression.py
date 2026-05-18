"""Regression tests for known production bugs. Moto-based, no LLM calls."""
import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

import shared.db as db_module


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "stride-test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "stride-test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)


@pytest.fixture
def ddb():
    db_module._table = None
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="stride-test",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "gsi1pk", "AttributeType": "S"},
                {"AttributeName": "gsi1sk", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        db_module._table = None  # reset again after table creation so get_table() picks up mock
        yield boto3.resource("dynamodb", region_name="us-east-1").Table("stride-test")
    db_module._table = None


def test_bug_001_update_user_patterns_preserves_tone(ddb):
    """
    BUG-001: update_user_patterns() must not reset preferred_tone to 'balanced'
    when the user has explicitly set it to 'direct' or 'encouraging'.
    Fixed pre-v1.1.
    """
    from shared.tools import record_velocity, update_user_patterns

    user_id = "+15550000001"
    project_id = "proj-bug001"
    cycle_id = "cycle-bug001"

    # Seed pattern record with preferred_tone explicitly set to "direct"
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE",
        "preferred_tone": "direct",
        "avg_pace": Decimal("0"),
        "avg_completion_rate": Decimal("0"),
        "total_cycles": 0,
    })

    # Seed user record
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": "#METADATA",
        "phone": user_id, "onboarded": True,
    })

    # Seed project
    ddb.put_item(Item={
        "pk": f"USER#{user_id}", "sk": f"PROJECT#{project_id}",
        "gsi1pk": f"PROJECT#{project_id}", "gsi1sk": "#METADATA",
        "name": "Bug 001 Project", "project_id": project_id,
    })

    # Seed cycle with future dates to pass date validation
    ddb.put_item(Item={
        "pk": f"PROJECT#{project_id}", "sk": f"CYCLE#{cycle_id}",
        "gsi1pk": f"CYCLE#{cycle_id}", "gsi1sk": "#METADATA",
        "cycle_id": cycle_id, "project_id": project_id,
        "start_date": "2026-06-01", "end_date": "2026-06-07",
        "planned_points": 8,
    })

    record_velocity(
        cycle_id=cycle_id, project_id=project_id,
        planned_points=8, delivered_points=5, cycle_name="Week 1",
    )
    update_user_patterns(
        user_id=user_id, delivered_points=5, planned_points=8, new_blockers=[],
    )

    item = ddb.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "PATTERN#AGGREGATE"}
    ).get("Item", {})
    assert item.get("preferred_tone") == "direct", (
        f"BUG-001 regression: preferred_tone was reset to {item.get('preferred_tone')!r}"
    )

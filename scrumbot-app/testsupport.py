"""Shared test-only helpers (not production code).

Importable from both tests/ and evals/ via PYTHONPATH=. — keeps the mocked
DynamoDB schema defined in exactly one place so the two conftests can't drift
from production (single-table schema is the locked source of truth).
"""


def create_stride_table(client, table_name: str = "stride-test"):
    """Create a moto DynamoDB table matching the production single-table schema (pk/sk + gsi1)."""
    client.create_table(
        TableName=table_name,
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

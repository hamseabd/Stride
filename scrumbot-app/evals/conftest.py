import boto3
import pytest
from moto import mock_aws

import shared.db as db_module
from testsupport import create_stride_table


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires ANTHROPIC_API_KEY; skipped in PR CI")
    config.addinivalue_line("markers", "nightly: expensive LLM calls; only runs in nightly CI")


@pytest.fixture(autouse=True)
def _env(request, monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "stride-test")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "stride-test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    # Nightly L2 judge tests hit *real* Bedrock with OIDC-assumed credentials that
    # configure-aws-credentials@v5 exports as AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN.
    # Overwriting those with fake "testing" values would clobber the role and break auth,
    # so only inject dummy AWS creds for the deterministic moto-backed tests.
    if request.node.get_closest_marker("nightly") is None:
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def ddb():
    """Mocked DynamoDB table matching production single-table schema (pk/sk + gsi1).

    Resets db_module._table around the mock so get_table()'s cached boto3 Table
    can't leak a real handle into (or out of) the moto context.
    """
    db_module._table = None
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_stride_table(client)
        db_module._table = None  # re-reset so get_table() resolves inside the mock
        yield boto3.resource("dynamodb", region_name="us-east-1").Table("stride-test")
    db_module._table = None

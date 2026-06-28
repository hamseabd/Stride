import pytest
import boto3
from moto import mock_aws
from datetime import date, timedelta

from testsupport import create_stride_table

# Relative dates so fixtures never rot (create_project/create_work_cycle reject past dates).
_FUTURE_TARGET = (date.today() + timedelta(days=30)).isoformat()
_CYCLE_START = (date.today() + timedelta(days=1)).isoformat()
_CYCLE_END = (date.today() + timedelta(days=7)).isoformat()


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
    """Mocked DynamoDB table matching production schema."""
    import shared.db
    shared.db._table = None  # reset singleton so moto's mock is picked up
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_stride_table(client)
        yield boto3.resource("dynamodb", region_name="us-east-1").Table("stride-test")


@pytest.fixture
def user_id():
    return "+15551234567"


@pytest.fixture
def seeded_user(ddb, user_id):
    """Create a user record and return the user_id."""
    from shared.db import get_or_create_user, record_consent
    record_consent(user_id=user_id, phone=user_id)
    get_or_create_user(user_id=user_id, phone=user_id)
    return user_id


@pytest.fixture
def seeded_project(seeded_user):
    """Create a user + project, return (user_id, project_id)."""
    from shared.tools import create_project
    result = create_project(user_id=seeded_user, name="Portfolio", description="My portfolio site", target_date=_FUTURE_TARGET)
    return seeded_user, result["project_id"]


@pytest.fixture
def seeded_cycle(seeded_project):
    """Create user + project + cycle, return (user_id, project_id, cycle_id)."""
    from shared.tools import create_work_cycle
    user_id, project_id = seeded_project
    result = create_work_cycle(
        project_id=project_id, name="Week 1", goal="Design phase",
        start_date=_CYCLE_START, end_date=_CYCLE_END,
    )
    return user_id, project_id, result["cycle_id"]


@pytest.fixture
def seeded_task(seeded_cycle):
    """Create user + project + cycle + task, return (user_id, project_id, cycle_id, task_id)."""
    from shared.tools import create_task
    user_id, project_id, cycle_id = seeded_cycle
    result = create_task(title="Wireframes", description="Design wireframes", estimate="M", cycle_id=cycle_id)
    return user_id, project_id, cycle_id, result["task_id"]

"""Server-side tenant binding: the bound user always wins over a model-supplied id."""

from shared import tenant
from shared.tenant import bind_user, bound_user, enforce_user


def test_passthrough_when_nothing_bound():
    assert bound_user() is None
    assert enforce_user("+15550000001") == "+15550000001"


def test_binding_is_scoped_to_the_context():
    with bind_user("+15550000001"):
        assert bound_user() == "+15550000001"
    assert bound_user() is None


def test_matching_id_passes_silently(monkeypatch):
    warnings = []
    monkeypatch.setattr(tenant.logger, "warning", lambda *a, **k: warnings.append((a, k)))
    with bind_user("+15550000001"):
        assert enforce_user("+15550000001") == "+15550000001"
    assert warnings == []


def test_mismatch_returns_bound_id_and_logs(monkeypatch):
    warnings = []
    monkeypatch.setattr(tenant.logger, "warning", lambda *a, **k: warnings.append((a, k)))
    with bind_user("+15550000001"):
        assert enforce_user("+15550000009") == "+15550000001"
    assert len(warnings) == 1
    assert warnings[0][0] == ("tenant_mismatch",)
    assert warnings[0][1] == {"user_id": "+15550000001", "supplied_user_id": "+15550000009"}


def test_nested_bind_restores_outer():
    with bind_user("+15550000001"):
        with bind_user("+15550000002"):
            assert bound_user() == "+15550000002"
        assert bound_user() == "+15550000001"

"""Unit tests for the tos_current computation logic. We test the helper
directly with simple objects rather than spinning up the DB — this is a
pure logic test."""

from types import SimpleNamespace

from app.schemas.auth import compute_tos_current


def _user(tos_version=None, selected_org=None):
    return SimpleNamespace(
        tos_version=tos_version,
        tos_accepted_at=None,
        selected_organization=selected_org,
    )


def _org(overridden=False):
    return SimpleNamespace(legal_terms_overridden=overridden)


def test_tos_current_false_when_user_has_never_accepted(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user()) is False


def test_tos_current_false_when_user_accepted_old_version(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user(tos_version="2026-01-01")) is False


def test_tos_current_true_when_user_accepted_current_version(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user(tos_version="2026-04-27")) is True


def test_tos_current_true_when_gate_disabled(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", False)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user()) is True


def test_tos_current_true_when_org_overrides(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    overridden_org = _org(overridden=True)
    assert compute_tos_current(_user(selected_org=overridden_org)) is True


def test_tos_current_false_when_org_does_not_override_and_version_stale(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    org = _org(overridden=False)
    assert compute_tos_current(_user(selected_org=org)) is False

"""Unit tests for the notification delivery policy module (TD-0091c Phase 2)."""

import pytest

from app.models.notifications import NotificationEventType
from app.services.core.notifications.policy import (
    DEFAULT_POLICY,
    DeliveryPolicy,
    policy_for,
)


def test_default_policy_is_exhaustive_over_event_types():
    expected = {e.value for e in NotificationEventType}
    assert set(DEFAULT_POLICY.keys()) == expected


def test_policy_for_returns_email_true_for_invite_sent():
    p = policy_for("INVITE_SENT")
    assert p.in_app is True
    assert p.email is True


def test_policy_for_returns_email_false_for_run_completed():
    p = policy_for("RUN_COMPLETED")
    assert p.email is False


def test_policy_for_unknown_event_returns_safe_defaults():
    p = policy_for("UNKNOWN_FUTURE_EVENT")
    assert p == DeliveryPolicy()

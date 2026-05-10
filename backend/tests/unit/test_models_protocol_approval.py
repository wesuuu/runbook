import uuid
from datetime import datetime

import pytest

from app.models.science import (Protocol, ProtocolApprovalEvent,
                                ProtocolApprovalRequest, Run)


def test_protocol_has_approval_columns():
    p = Protocol(name="x", organization_id=uuid.uuid4())
    assert p.requires_approval is False or p.requires_approval is None
    assert hasattr(p, "created_by_id")
    assert hasattr(p, "approved_by_id")
    assert hasattr(p, "approved_at")


def test_run_has_is_strict_column():
    r = Run(name="x", project_id=uuid.uuid4())
    assert r.is_strict is False or r.is_strict is None


def test_event_action_constants():
    e = ProtocolApprovalEvent(
        protocol_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        action="SUBMITTED",
    )
    assert e.action == "SUBMITTED"


def test_request_status_default():
    r = ProtocolApprovalRequest(
        protocol_id=uuid.uuid4(),
        requested_user_id=uuid.uuid4(),
        requested_by_id=uuid.uuid4(),
    )
    assert r.status in (None, "OPEN")

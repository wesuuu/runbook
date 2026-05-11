import uuid

from app.models.science import (Protocol, ProtocolApprovalAction,
                                ProtocolApprovalEvent, ProtocolApprovalRequest,
                                ProtocolApprovalRequestStatus, Run)


def test_protocol_has_approval_columns():
    p = Protocol(name="x", organization_id=uuid.uuid4())
    # Defaults apply at INSERT time, not __init__; columns must exist.
    assert hasattr(p, "requires_approval")
    assert hasattr(p, "created_by_id")
    assert hasattr(p, "approved_by_id")
    assert hasattr(p, "approved_at")


def test_run_has_is_strict_column():
    r = Run(name="x", project_id=uuid.uuid4())
    assert hasattr(r, "is_strict")


def test_event_action_constants():
    e = ProtocolApprovalEvent(
        protocol_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        action=ProtocolApprovalAction.SUBMITTED,
    )
    assert e.action == "SUBMITTED"
    assert e.comment is None
    assert e.signature_statement is None
    assert e.protocol_version_id is None


def test_request_status_uses_enum():
    r = ProtocolApprovalRequest(
        protocol_id=uuid.uuid4(),
        requested_user_id=uuid.uuid4(),
        requested_by_id=uuid.uuid4(),
        status=ProtocolApprovalRequestStatus.OPEN,
    )
    assert r.status == "OPEN"

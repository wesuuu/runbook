"""Approval-related chat schemas (F-0084)."""

import uuid

from app.schemas.chat import (
    ApprovalRequest,
    ApprovalRequiredEvent,
    ExternalProtocolPayloadPreview,
)


def test_approval_required_event_validates():
    ev = ApprovalRequiredEvent(
        type="approval_required",
        tool_call_id="call_abc",
        tool_name="create_protocol_from_external_source",
        title="X",
        source_url="https://openwetware.org/wiki/X",
        assistant_message_id=uuid.uuid4(),
        payload_preview=ExternalProtocolPayloadPreview(
            title="X",
            source_url="https://openwetware.org/wiki/X",
            step_count=7,
            duration_min_total=110,
            license="CC BY-SA 3.0",
        ),
    )
    assert ev.type == "approval_required"


def test_approval_request_requires_fields():
    req = ApprovalRequest(tool_call_id="call_abc", approved=True)
    assert req.approved is True

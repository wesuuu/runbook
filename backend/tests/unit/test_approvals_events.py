"""Unit tests for the approvals event helpers."""

import uuid

import pytest

from app.models.science import Protocol
from app.services.approvals import VALID_ACTIONS, fulfill_open_requests, write_event


@pytest.mark.asyncio
async def test_write_event_validates_action():
    proto = Protocol(name="x", organization_id=uuid.uuid4())
    with pytest.raises(ValueError):
        await write_event(
            None,  # type: ignore[arg-type]
            protocol=proto,
            actor_id=uuid.uuid4(),
            action="BOGUS",
        )


@pytest.mark.asyncio
async def test_fulfill_open_requests_validates_status():
    with pytest.raises(ValueError):
        await fulfill_open_requests(
            None,  # type: ignore[arg-type]
            protocol_id=uuid.uuid4(),
            final_status="NONSENSE",
            actor_id=None,
        )


def test_valid_actions_constant():
    assert set(VALID_ACTIONS) == {"SUBMITTED", "APPROVED", "REJECTED", "REVERTED"}

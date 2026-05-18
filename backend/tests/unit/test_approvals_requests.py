"""Unit tests for the approvals request-fulfillment helper."""

import uuid

import pytest

from app.services.approvals import VALID_FULFILL_STATES, fulfill_open_requests


@pytest.mark.asyncio
async def test_fulfill_open_requests_validates_status():
    with pytest.raises(ValueError):
        await fulfill_open_requests(
            None,  # type: ignore[arg-type]
            protocol_id=uuid.uuid4(),
            final_status="NONSENSE",
            actor_id=None,
        )


def test_valid_fulfill_states_constant():
    assert set(VALID_FULFILL_STATES) == {"APPROVED", "REJECTED", "WITHDRAWN"}

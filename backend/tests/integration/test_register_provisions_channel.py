"""TD-0091c: User after_insert queues pending provisioning + drains on commit.

The full background-task path (fire-and-forget asyncio.create_task) opens an
isolated AsyncSessionLocal which can't see the test SAVEPOINT's data, so we
verify the *wiring* here -- that inserting a User queues its id and that the
after_commit handler drains the queue and submits to the task runner.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.iam import User


@pytest.mark.asyncio
async def test_user_insert_queues_pending_default_channel(db_session):
    user = User(email=f"queue-{uuid4().hex[:8]}@example.com", email_verified=False)
    db_session.add(user)
    await db_session.flush()

    pending = db_session.sync_session.info.get("pending_default_channels", [])
    assert user.id in pending


@pytest.mark.asyncio
async def test_after_commit_drains_queue_and_submits(db_session):
    user = User(email=f"drain-{uuid4().hex[:8]}@example.com", email_verified=False)
    db_session.add(user)
    await db_session.flush()

    with patch(
        "app.services.core.task_runner.get_task_runner"
    ) as mock_runner_factory:
        mock_runner = mock_runner_factory.return_value
        await db_session.commit()

    mock_runner.submit.assert_called_once()
    # After drain, the queue should be empty
    pending = db_session.sync_session.info.get("pending_default_channels", [])
    assert pending == []

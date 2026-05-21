"""Turn-liveness heartbeat for chat sessions (BUG-005).

While a chat turn runs it stamps a heartbeat onto its ``ChatSession``.
``GET /chat/sessions/{id}`` exposes a derived ``turn_in_progress`` boolean so
the frontend poll-recovery path can distinguish a slow-but-healthy turn from a
genuinely orphaned one — instead of guessing with a fixed client-side timeout.
Mirrors the ``BackgroundJob.heartbeat_at`` liveness pattern.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import update

from app.db.session import AsyncSessionLocal
from app.models.chat import ChatSession

logger = logging.getLogger(__name__)

# How often a running turn refreshes its heartbeat.
TURN_HEARTBEAT_INTERVAL_S = 15
# A heartbeat older than this means no turn is live (worker died / orphaned).
TURN_STALE_AFTER_S = 60


def is_turn_in_progress(heartbeat_at: datetime | None) -> bool:
    """Return True iff a heartbeat exists and is younger than TURN_STALE_AFTER_S."""
    if heartbeat_at is None:
        return False
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - heartbeat_at
    return age < timedelta(seconds=TURN_STALE_AFTER_S)


async def _write_heartbeat(session_id: UUID, value: datetime | None) -> None:
    """Set chat_sessions.active_turn_heartbeat_at on a fresh writer session."""
    async with AsyncSessionLocal() as writer:
        await writer.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(active_turn_heartbeat_at=value)
        )
        await writer.commit()


async def clear_turn_heartbeat(session_id: UUID) -> None:
    """Clear the session's turn heartbeat to NULL.

    Completion and HITL-pause paths fold the clear into their existing
    writer ``update(ChatSession)`` so it is atomic with the state change.
    Error / early-return paths have no such UPDATE of their own and call
    this helper explicitly so they never leave a phantom live heartbeat.
    """
    await _write_heartbeat(session_id, None)


@asynccontextmanager
async def turn_heartbeat(session_id: UUID) -> AsyncIterator[None]:
    """Keep the session's turn heartbeat fresh for the duration of the block.

    The caller sets the *initial* heartbeat in the same commit as the user
    message (race-free turn start) and *clears* it to NULL when the assistant
    message is persisted. This context manager only refreshes a long-running
    turn's heartbeat every TURN_HEARTBEAT_INTERVAL_S and stops on exit. It
    does NOT clear the column on exit — clearing there would race the happy
    path (the drain loop can end before the assistant message is persisted).
    """

    async def _beat() -> None:
        while True:
            await asyncio.sleep(TURN_HEARTBEAT_INTERVAL_S)
            try:
                await _write_heartbeat(session_id, datetime.now(timezone.utc))
            except Exception:  # best-effort liveness write
                logger.warning(
                    "turn heartbeat refresh failed for session %s", session_id
                )

    task = asyncio.create_task(_beat())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

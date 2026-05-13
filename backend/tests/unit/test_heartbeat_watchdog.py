"""Watchdog kills the subprocess after N consecutive missed heartbeats
and marks the Document FAILED."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.documents.extraction.heartbeat_watchdog import HeartbeatWatchdog


@pytest.mark.asyncio
async def test_watchdog_kills_after_max_misses(async_session, seed_document_extracting):
    doc = seed_document_extracting
    doc.heartbeat_token = "tok"
    doc.last_heartbeat_at = None  # never beat
    await async_session.commit()

    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()

    watchdog = HeartbeatWatchdog(
        document_id=doc.id,
        proc=proc,
        interval_seconds=0.05,
        max_misses=3,
        session_factory=lambda: async_session,
    )
    await watchdog.run_until_dead_or_done()

    assert proc.kill.called
    assert watchdog.timed_out is True


@pytest.mark.asyncio
async def test_watchdog_resets_on_fresh_heartbeat(async_session, seed_document_extracting):
    doc = seed_document_extracting
    doc.heartbeat_token = "tok"
    doc.last_heartbeat_at = datetime.now(timezone.utc)
    await async_session.commit()

    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()

    # Keep bumping the heartbeat every interval so the watchdog never
    # accumulates enough consecutive misses to fire.
    stop_bumping = asyncio.Event()

    async def bump_heartbeat():
        while not stop_bumping.is_set():
            doc.last_heartbeat_at = datetime.now(timezone.utc)
            await async_session.commit()
            await asyncio.sleep(0.04)  # bump faster than the watchdog interval

    watchdog = HeartbeatWatchdog(
        document_id=doc.id,
        proc=proc,
        interval_seconds=0.05,
        max_misses=3,
        session_factory=lambda: async_session,
    )

    async def stop_after_short_run():
        await asyncio.sleep(0.4)
        stop_bumping.set()
        proc.returncode = 0  # subprocess "exited normally"

    await asyncio.gather(
        watchdog.run_until_dead_or_done(),
        bump_heartbeat(),
        stop_after_short_run(),
    )

    assert not proc.kill.called
    assert watchdog.timed_out is False

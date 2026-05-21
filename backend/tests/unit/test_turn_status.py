"""Unit tests for the chat turn-liveness heartbeat (BUG-005)."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.services.ai.turn_status as ts
from app.services.ai.turn_status import (
    TURN_STALE_AFTER_S,
    clear_turn_heartbeat,
    is_turn_in_progress,
    turn_heartbeat,
)


def test_is_turn_in_progress_none_is_false():
    assert is_turn_in_progress(None) is False


def test_is_turn_in_progress_fresh_is_true():
    assert is_turn_in_progress(datetime.now(timezone.utc)) is True


def test_is_turn_in_progress_stale_is_false():
    stale = datetime.now(timezone.utc) - timedelta(seconds=TURN_STALE_AFTER_S + 5)
    assert is_turn_in_progress(stale) is False


def test_is_turn_in_progress_at_threshold_is_false():
    # An age exactly equal to the threshold is NOT in progress: the
    # predicate is a strict `age < timedelta(...)`. Probe just inside the
    # boundary (the test clock advances between construction and the call).
    boundary = datetime.now(timezone.utc) - timedelta(seconds=TURN_STALE_AFTER_S)
    assert is_turn_in_progress(boundary) is False


def test_is_turn_in_progress_naive_timestamp_treated_as_utc():
    # Defensive: production values are tz-aware (TIMESTAMPTZ via asyncpg).
    # If a naive datetime ever reaches the predicate it is assumed UTC
    # rather than raising on the aware/naive subtraction.
    assert is_turn_in_progress(datetime.utcnow()) is True


@pytest.mark.asyncio
async def test_turn_heartbeat_refreshes_then_stops_on_exit():
    beats: list = []

    async def _fake_write(session_id, value):
        beats.append(value)

    with (
        patch.object(ts, "TURN_HEARTBEAT_INTERVAL_S", 0.01),
        patch.object(ts, "_write_heartbeat", AsyncMock(side_effect=_fake_write)),
    ):
        async with turn_heartbeat(uuid.uuid4()):
            await asyncio.sleep(0.05)
        beats_during = len(beats)

    assert beats_during >= 1
    await asyncio.sleep(0.03)
    assert len(beats) == beats_during  # no refresh after the block exits


@pytest.mark.asyncio
async def test_clear_turn_heartbeat_writes_none():
    sid = uuid.uuid4()
    with patch.object(ts, "_write_heartbeat", AsyncMock()) as mock_write:
        await clear_turn_heartbeat(sid)
    mock_write.assert_awaited_once_with(sid, None)

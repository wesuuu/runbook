"""Unit tests for the periodic recovery loop (TD-0085 Phase 3)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_recovery_loop_runs_both_sweeps_each_tick():
    """One iteration calls both sweep functions in order."""
    from app.main import _recovery_loop

    jobs = AsyncMock()
    docs = AsyncMock()
    with patch("app.main._recover_stalled_jobs", jobs), \
         patch("app.main._recover_stalled_documents", docs), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0.01

        task = asyncio.create_task(_recovery_loop())
        await asyncio.sleep(0.05)  # let it tick a few times
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert jobs.await_count >= 1
    assert docs.await_count >= 1


@pytest.mark.asyncio
async def test_recovery_loop_swallows_sweep_exceptions():
    """A sweep raising should not kill the loop."""
    from app.main import _recovery_loop

    calls = []

    async def boom():
        calls.append("boom")
        raise RuntimeError("simulated DB blip")

    async def ok():
        calls.append("ok")

    with patch("app.main._recover_stalled_jobs", boom), \
         patch("app.main._recover_stalled_documents", ok), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0.01

        task = asyncio.create_task(_recovery_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Each iteration: boom (raises), then ok still runs.
    assert calls.count("boom") >= 2
    assert calls.count("ok") >= 2


@pytest.mark.asyncio
async def test_recovery_loop_disabled_when_interval_is_zero():
    from app.main import _recovery_loop

    jobs = AsyncMock()
    docs = AsyncMock()
    with patch("app.main._recover_stalled_jobs", jobs), \
         patch("app.main._recover_stalled_documents", docs), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0

        # Should return immediately.
        await asyncio.wait_for(_recovery_loop(), timeout=0.2)

    assert jobs.await_count == 0
    assert docs.await_count == 0

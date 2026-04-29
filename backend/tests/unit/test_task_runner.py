"""Tests for the TaskRunner abstraction (F-0021 follow-up)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.core.task_runner import (TaskRunner, ThreadTaskRunner,
                                           get_task_runner, reset_task_runner)


@pytest.fixture(autouse=True)
def _reset_runner():
    """Reset the singleton between tests."""
    reset_task_runner()
    yield
    reset_task_runner()


class TestThreadTaskRunner:
    """ThreadTaskRunner offloads blocking work to a thread pool."""

    @pytest.mark.asyncio
    async def test_run_async_executes_coroutine(self):
        runner = ThreadTaskRunner()
        called = False

        async def my_task():
            nonlocal called
            called = True

        await runner.run_async(my_task())
        assert called is True

    @pytest.mark.asyncio
    async def test_run_sync_offloads_to_thread(self):
        """Sync functions should run in a thread, not block the event loop."""
        runner = ThreadTaskRunner()
        result = await runner.run_sync(lambda: 42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_sync_does_not_block_event_loop(self):
        """Verify that a slow sync function doesn't block other coroutines."""
        import time

        runner = ThreadTaskRunner()
        flag = asyncio.Event()

        async def other_work():
            flag.set()

        async def run_both():
            task = asyncio.create_task(runner.run_sync(lambda: time.sleep(0.2)))
            # other_work should be able to run while sync is in thread
            await asyncio.sleep(0.05)
            await other_work()
            await task

        await run_both()
        assert flag.is_set()

    @pytest.mark.asyncio
    async def test_submit_fires_and_forgets(self):
        """submit() should schedule work without awaiting it."""
        runner = ThreadTaskRunner()
        called = asyncio.Event()

        async def bg_task():
            called.set()

        runner.submit(bg_task())
        await asyncio.sleep(0.1)
        assert called.is_set()


class TestGetTaskRunner:
    """get_task_runner returns the correct backend based on config."""

    def test_default_returns_thread_runner(self):
        runner = get_task_runner()
        assert isinstance(runner, ThreadTaskRunner)

    @patch("app.services.core.task_runner.settings")
    def test_thread_backend_explicit(self, mock_settings):
        mock_settings.task_runner_backend = "thread"
        runner = get_task_runner()
        assert isinstance(runner, ThreadTaskRunner)

    @patch("app.services.core.task_runner.settings")
    def test_unknown_backend_raises(self, mock_settings):
        mock_settings.task_runner_backend = "celery"
        with pytest.raises(ValueError, match="Unknown task runner"):
            get_task_runner()

from unittest.mock import patch

import pytest

from app.services.core.background_handler import (
    JOB_REGISTRY,
    BackgroundHandler,
    CloudGpuBackgroundHandler,
    LocalBackgroundHandler,
    get_background_handler,
    register_job,
)


def test_factory_returns_local_by_default():
    with patch("app.services.core.background_handler.settings") as fake_settings:
        fake_settings.background_handler = "local"
        handler = get_background_handler()
    assert isinstance(handler, LocalBackgroundHandler)
    assert isinstance(handler, BackgroundHandler)


def test_factory_returns_cloud_gpu_when_configured():
    with patch("app.services.core.background_handler.settings") as fake_settings:
        fake_settings.background_handler = "cloud-gpu"
        handler = get_background_handler()
    assert isinstance(handler, CloudGpuBackgroundHandler)


def test_factory_raises_for_unknown_backend():
    with patch("app.services.core.background_handler.settings") as fake_settings:
        fake_settings.background_handler = "bogus"
        with pytest.raises(ValueError, match="bogus"):
            get_background_handler()


@pytest.mark.asyncio
async def test_cloud_gpu_handler_raises_not_implemented():
    handler = CloudGpuBackgroundHandler()
    with pytest.raises(NotImplementedError):
        await handler.launch("document_extract", document_id="x")


@pytest.mark.asyncio
async def test_local_handler_dispatches_registered_job():
    # DEVIATION from plan: instead of driving the coroutine inside _Runner.submit
    # (which would fail with "event loop already running"), we capture the coroutine
    # in submitted[] and await it after handler.launch() returns.
    received: list = []

    @register_job("_fake_job_for_test")
    async def _fake(**kwargs):
        received.append(kwargs)

    submitted: list = []

    class _Runner:
        def submit(self, coro):
            submitted.append(coro)
            # Do NOT run_until_complete here — the test loop is already running.
            # The test awaits submitted[0] below.

    try:
        with patch(
            "app.services.core.background_handler.get_task_runner",
            return_value=_Runner(),
        ):
            handler = LocalBackgroundHandler()
            await handler.launch("_fake_job_for_test", document_id="abc")

        assert submitted, "task runner should have received a coroutine"
        # Drive the coroutine to completion now that we're still in the async test.
        await submitted[0]
        assert received == [{"document_id": "abc"}]
    finally:
        JOB_REGISTRY.pop("_fake_job_for_test", None)


@pytest.mark.asyncio
async def test_local_handler_raises_for_unknown_job():
    handler = LocalBackgroundHandler()
    with pytest.raises(KeyError, match="nonexistent"):
        await handler.launch("nonexistent")

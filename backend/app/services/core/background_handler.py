"""Generic background-job dispatch abstraction.

Provides a strategy pattern so the app can swap between:
  - LocalBackgroundHandler (default): dispatches registered async jobs
    to the in-process TaskRunner (fire-and-forget via create_task).
  - CloudGpuBackgroundHandler (stub): raises NotImplementedError until
    a cloud GPU queue (e.g., Modal, RunPod) is wired up.

Usage::

    from app.services.core.background_handler import get_background_handler

    handler = get_background_handler()
    await handler.launch("document_extract", document_id=doc.id)

Registering a job::

    from app.services.core.background_handler import register_job

    @register_job("document_extract")
    async def run_extraction(document_id: UUID) -> None:
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict

from app.core.config import settings
from app.services.core.task_runner import get_task_runner

JobFn = Callable[..., Awaitable[None]]

JOB_REGISTRY: Dict[str, JobFn] = {}


def register_job(name: str) -> Callable[[JobFn], JobFn]:
    """Decorator that registers an async function under ``name`` in JOB_REGISTRY.

    Raises RuntimeError if ``name`` is already taken by a different function
    (idempotent re-registration of the same function is allowed so modules
    can be reloaded without errors).
    """

    def decorator(fn: JobFn) -> JobFn:
        if name in JOB_REGISTRY and JOB_REGISTRY[name] is not fn:
            raise RuntimeError(f"job {name!r} already registered")
        JOB_REGISTRY[name] = fn
        return fn

    return decorator


class BackgroundHandler(ABC):
    """Abstract interface for background-job execution backends."""

    @abstractmethod
    async def launch(self, job: str, **kwargs: Any) -> None:
        """Schedule ``job`` for execution with ``kwargs`` as arguments."""
        ...


class LocalBackgroundHandler(BackgroundHandler):
    """Dispatches registered jobs to the in-process TaskRunner.

    The coroutine is submitted via ``runner.submit(coro)`` which calls
    ``asyncio.create_task`` — fire-and-forget, does not await completion.
    """

    async def launch(self, job: str, **kwargs: Any) -> None:
        if job not in JOB_REGISTRY:
            raise KeyError(f"no job registered under name {job!r}")
        fn = JOB_REGISTRY[job]
        runner = get_task_runner()
        runner.submit(fn(**kwargs))


class CloudGpuBackgroundHandler(BackgroundHandler):
    """Stub for a future cloud-GPU job queue (e.g., Modal, RunPod).

    Raises NotImplementedError until the cloud integration is wired up.
    """

    async def launch(self, job: str, **kwargs: Any) -> None:
        raise NotImplementedError("cloud-gpu background handler not implemented yet")


def get_background_handler() -> BackgroundHandler:
    """Return a BackgroundHandler instance for the configured backend.

    Reads ``settings.background_handler``:
      - ``"local"``      → LocalBackgroundHandler
      - ``"cloud-gpu"``  → CloudGpuBackgroundHandler
      - anything else    → ValueError
    """
    backend = settings.background_handler
    if backend == "local":
        return LocalBackgroundHandler()
    if backend == "cloud-gpu":
        return CloudGpuBackgroundHandler()
    raise ValueError(f"unknown background_handler: {backend!r}")

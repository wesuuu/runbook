"""Pluggable task runner abstraction for background processing.

Provides a strategy pattern so the app can swap between:
  - ThreadTaskRunner (default): offloads CPU-bound work to asyncio's
    thread pool, keeps everything in-process. Good for dev / single-pod.
  - Future backends (e.g., Kubernetes Job, Celery) can be added by
    subclassing TaskRunner and registering in get_task_runner().

Usage in endpoints / services:
    from app.services.task_runner import get_task_runner

    runner = get_task_runner()
    runner.submit(process_document(doc.id, db_url))   # fire-and-forget
    result = await runner.run_sync(extract_pdf, path)  # offload blocking fn
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Shared thread pool for CPU-bound work. sized to leave headroom for
# the event loop; can be tuned via RUNBOOK_TASK_RUNNER_POOL_SIZE.
_pool: ThreadPoolExecutor | None = None


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        size = getattr(settings, "task_runner_pool_size", 4)
        _pool = ThreadPoolExecutor(max_workers=size, thread_name_prefix="doc-worker")
    return _pool


class TaskRunner(ABC):
    """Abstract interface for background task execution."""

    @abstractmethod
    async def run_async(self, coro: Awaitable[T]) -> T:
        """Await an async coroutine (may run in-process or remotely)."""
        ...

    @abstractmethod
    async def run_sync(self, fn: Callable[..., T], *args: Any) -> T:
        """Run a blocking/CPU-bound function off the event loop."""
        ...

    @abstractmethod
    def submit(self, coro: Awaitable[Any]) -> None:
        """Fire-and-forget: schedule async work without awaiting it."""
        ...


class ThreadTaskRunner(TaskRunner):
    """Runs tasks in-process using asyncio + a thread pool.

    - run_async: awaits the coroutine on the current event loop.
    - run_sync: dispatches to a ThreadPoolExecutor so the event loop
      stays free during CPU-bound extraction / chunking.
    - submit: wraps the coroutine in asyncio.create_task (fire-and-forget).
    """

    async def run_async(self, coro: Awaitable[T]) -> T:
        return await coro

    async def run_sync(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_get_pool(), fn, *args)

    def submit(self, coro: Awaitable[Any]) -> None:
        asyncio.create_task(coro)


# -- Factory ----------------------------------------------------------

_runner: TaskRunner | None = None


def get_task_runner() -> TaskRunner:
    """Return the singleton TaskRunner for the configured backend."""
    global _runner
    if _runner is not None:
        return _runner

    backend = getattr(settings, "task_runner_backend", "thread")

    if backend == "thread":
        _runner = ThreadTaskRunner()
    else:
        raise ValueError(
            f"Unknown task runner backend: {backend!r}. "
            "Supported: 'thread'. Future: 'kubernetes', 'celery'."
        )

    logger.info("Task runner initialized: %s", type(_runner).__name__)
    return _runner


def reset_task_runner() -> None:
    """Reset the singleton (for testing)."""
    global _runner
    _runner = None

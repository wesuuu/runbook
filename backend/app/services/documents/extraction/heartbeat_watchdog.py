"""Async watchdog that fails extractions whose subprocess stops sending
heartbeats. Polls Document.last_heartbeat_at every `interval_seconds`;
after `max_misses` consecutive polls with no fresh timestamp, kills the
subprocess. Caller is responsible for marking the row FAILED.

Termination conditions (any → exit the loop):
  - subprocess has exited (proc.returncode is not None) → timed_out=False
  - max_misses reached                                  → timed_out=True
  - external cancellation via stop()                    → timed_out=False
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Document

logger = logging.getLogger(__name__)


class HeartbeatWatchdog:
    def __init__(
        self,
        *,
        document_id: UUID,
        proc,  # asyncio.subprocess.Process — typed loosely for testability
        interval_seconds: float,
        max_misses: int,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self._document_id = document_id
        self._proc = proc
        self._interval = interval_seconds
        self._max_misses = max_misses
        self._session_factory = session_factory
        self._stop = asyncio.Event()
        self.timed_out = False

    def stop(self) -> None:
        self._stop.set()

    async def run_until_dead_or_done(self) -> None:
        misses = 0
        last_seen: datetime | None = None
        while not self._stop.is_set():
            if self._proc.returncode is not None:
                return  # subprocess finished on its own
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except asyncio.TimeoutError:
                pass

            current = await self._read_heartbeat()
            if current is None or current == last_seen:
                misses += 1
                logger.debug(
                    "heartbeat miss %d/%d for document %s",
                    misses, self._max_misses, self._document_id,
                )
            else:
                misses = 0
                last_seen = current

            if misses >= self._max_misses:
                self.timed_out = True
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
                return

    async def _read_heartbeat(self) -> datetime | None:
        session = self._session_factory()
        try:
            # expire_all() clears the identity map cache so we always
            # get a fresh read from the DB (important when the factory
            # returns the same session across multiple calls, e.g. in tests).
            session.expire_all()
            result = await session.execute(
                select(Document.last_heartbeat_at).where(
                    Document.id == self._document_id
                )
            )
            return result.scalar_one_or_none()
        finally:
            # Tests pass an existing session; the production caller creates one per call.
            # We never close the session here — ownership belongs to the factory.
            pass

"""In-process token-bucket rate limiter for external-protocol connectors.

Keyed by ``(org_id, source)`` so OpenWetWare and protocols.io draw on
separate per-org budgets. Single-replica deploy assumption — see the
F-0084 / F-0090 risk notes; revisit when we go multi-worker.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable
from uuid import UUID

# Test-injectable monotonic clock — tests override this.
_now: Callable[[], float] = time.monotonic

# Per-(org, source) timestamps for the trailing 60s window.
_RECENT_REQUESTS: dict[tuple[UUID, str], deque[float]] = {}
_LIMIT_LOCK = asyncio.Lock()


async def check_rate_limit(org_id: UUID, source: str, limit: int) -> None:
    """Record a call to ``source`` for ``org_id``; raise if over ``limit``.

    Raises:
        ValueError: when ``org_id`` has already made ``limit`` calls to
            ``source`` within the trailing 60-second window.
    """
    async with _LIMIT_LOCK:
        now = _now()
        bucket = _RECENT_REQUESTS.setdefault((org_id, source), deque())
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ValueError(
                f"{source} rate limit hit ({limit}/min). Try again in a minute."
            )
        bucket.append(now)

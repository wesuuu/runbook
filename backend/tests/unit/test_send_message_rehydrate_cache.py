"""Regression: external_protocol_cache persistence on chat_sessions.

The cache survives across requests via a JSONB column on ChatSession
(populated by the subagent on fetch, loaded into ChatDeps at the start
of each turn, flushed back to the DB at every history-write point).
Previously it was rehydrated by scraping EXTERNAL_PROTOCOL_SOURCE fence
blocks out of ai_message_history, but pydantic-ai compaction elides
large tool returns and the LLM sometimes drops the fence label.

These tests cover the LRU-style trim helper that keeps the per-session
cache bounded at flush time.
"""

from __future__ import annotations

from app.services.ai.send_message import (
    _EXTERNAL_PROTOCOL_CACHE_MAX,
    _trim_external_protocol_cache,
)


def test_trim_noop_when_under_cap():
    cache = {f"https://openwetware.org/wiki/p{i}": "{}" for i in range(5)}
    assert _trim_external_protocol_cache(cache) is cache
    assert len(cache) == 5


def test_trim_noop_at_exact_cap():
    cache = {
        f"https://openwetware.org/wiki/p{i}": "{}"
        for i in range(_EXTERNAL_PROTOCOL_CACHE_MAX)
    }
    out = _trim_external_protocol_cache(cache)
    assert len(out) == _EXTERNAL_PROTOCOL_CACHE_MAX


def test_trim_drops_oldest_when_over_cap():
    cache: dict[str, str] = {}
    for i in range(_EXTERNAL_PROTOCOL_CACHE_MAX + 3):
        cache[f"https://openwetware.org/wiki/p{i}"] = f'{{"i": {i}}}'

    out = _trim_external_protocol_cache(cache)

    assert len(out) == _EXTERNAL_PROTOCOL_CACHE_MAX
    # First three (oldest by insertion order) should be gone.
    assert "https://openwetware.org/wiki/p0" not in out
    assert "https://openwetware.org/wiki/p1" not in out
    assert "https://openwetware.org/wiki/p2" not in out
    # Newest entry should still be there.
    last_key = f"https://openwetware.org/wiki/p{_EXTERNAL_PROTOCOL_CACHE_MAX + 2}"
    assert last_key in out


def test_trim_handles_empty_cache():
    cache: dict[str, str] = {}
    out = _trim_external_protocol_cache(cache)
    assert out == {}

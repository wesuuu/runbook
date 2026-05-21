"""HTTP tools, host allowlist, feature flag, rate limit (F-0084)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import openwetware, rate_limit
from app.services.ai.subagents.protocol_knowledgebase import tools as kb


async def _noop_sleep(*_args, **_kwargs):
    """Stand-in for asyncio.sleep so the retry backoff doesn't slow tests."""

FIX_DIR = Path(__file__).parent.parent / "fixtures" / "openwetware"


@dataclass
class _FakeDeps:
    org_id: UUID
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    external_protocol_cache: dict = field(default_factory=dict)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


def _fake_get(json_path: Path):
    payload = json.loads(json_path.read_text())

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, timeout=None):
        return _Resp()

    return _get


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    rate_limit._RECENT_REQUESTS.clear()
    yield
    rate_limit._RECENT_REQUESTS.clear()


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)
    monkeypatch.setattr(
        settings.features.external_protocols.openwetware, "rate_limit_per_minute", 10
    )
    yield


@pytest.mark.asyncio
async def test_search_disabled_when_flag_off():
    settings.features.external_protocols.enabled = False
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with pytest.raises(ValueError, match="disabled"):
        await kb.search_openwetware(ctx, "anything")


@pytest.mark.asyncio
async def test_search_disabled_when_openwetware_source_off(_enabled, monkeypatch):
    monkeypatch.setattr(
        settings.features.external_protocols.openwetware, "enabled", False
    )
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with pytest.raises(ValueError, match="OpenWetWare source is disabled"):
        await kb.search_openwetware(ctx, "anything")


@pytest.mark.asyncio
async def test_fetch_rejects_non_openwetware_host(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with pytest.raises(ValueError, match="openwetware.org"):
        await kb.fetch_openwetware_protocol(ctx, "https://example.com/wiki/foo")


@pytest.mark.asyncio
async def test_search_returns_hits_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with patch(
        "httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "opensearch_response.json")
    ):
        result = await kb.search_openwetware(ctx, "transformation of e. coli", limit=3)
    assert result.total == 1
    assert result.hits[0].url.startswith("https://openwetware.org/wiki/")
    assert ctx.deps.tool_calls[-1]["tool"] == "search_openwetware"


@pytest.mark.asyncio
async def test_fetch_returns_payload_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    url = "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"
    with patch("httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "parse_response.json")):
        payload = await kb.fetch_openwetware_protocol(ctx, url)
    assert payload.source_url == url
    assert len(payload.steps) == 7
    assert payload.steps[2].duration_min == 2  # 90 s -> ceil(1.5)
    assert ctx.deps.tool_calls[-1]["tool"] == "fetch_openwetware_protocol"
    assert ctx.deps.tool_calls[-1]["source_url"] == url


@pytest.mark.asyncio
async def test_search_recovers_when_source_unreachable(_enabled, monkeypatch):
    """A flaky OpenWetWare connection must not bubble an exception through
    the task tool — search returns total=0 with an outage message so the
    subagent can report it instead of the parent re-dispatching in a loop."""
    monkeypatch.setattr(openwetware.asyncio, "sleep", _noop_sleep)

    async def _raise(self, url, params=None, timeout=None):
        raise httpx.ConnectError("connection reset")

    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with patch("httpx.AsyncClient.get", new=_raise):
        result = await kb.search_openwetware(ctx, "agarose gel electrophoresis")
    assert result.total == 0
    assert result.message and "unreachable" in result.message.lower()


@pytest.mark.asyncio
async def test_fetch_recovers_when_source_unreachable(_enabled, monkeypatch):
    """A transport failure on fetch returns a recoverable payload (error set,
    no steps) so the subagent reports the outage rather than crashing."""
    monkeypatch.setattr(openwetware.asyncio, "sleep", _noop_sleep)

    async def _raise(self, url, params=None, timeout=None):
        raise httpx.ReadTimeout("timed out")

    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    url = "https://openwetware.org/wiki/Agarose_gel_electrophoresis"
    with patch("httpx.AsyncClient.get", new=_raise):
        payload = await kb.fetch_openwetware_protocol(ctx, url)
    assert payload.steps == []
    assert payload.error and "unreachable" in payload.error.lower()


@pytest.mark.asyncio
async def test_fetch_populates_external_protocol_cache(_enabled):
    """Regression: payload is a @dataclass — serialisation must use
    ``dataclasses.asdict`` + ``json.dumps``, not ``model_dump_json``.
    The latter silently raises AttributeError and was being swallowed,
    leaving the cache empty and the approval card showing 0 steps."""
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    url = "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"
    with patch("httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "parse_response.json")):
        await kb.fetch_openwetware_protocol(ctx, url)
    assert url in ctx.deps.external_protocol_cache
    cached_json = ctx.deps.external_protocol_cache[url]
    cached = json.loads(cached_json)
    assert cached["source_url"] == url
    assert isinstance(cached["steps"], list)
    assert len(cached["steps"]) == 7
    assert "text" in cached["steps"][0]


@pytest.mark.asyncio
async def test_rate_limit_trips_after_threshold(_enabled, monkeypatch):
    monkeypatch.setattr(
        settings.features.external_protocols.openwetware, "rate_limit_per_minute", 2
    )
    org = uuid4()
    fake_now = {"t": 0.0}
    monkeypatch.setattr(rate_limit, "_now", lambda: fake_now["t"])
    ctx = _FakeCtx(deps=_FakeDeps(org_id=org))
    with patch(
        "httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "opensearch_response.json")
    ):
        await kb.search_openwetware(ctx, "q")
        fake_now["t"] = 1.0
        await kb.search_openwetware(ctx, "q")
        fake_now["t"] = 2.0
        with pytest.raises(ValueError, match="rate limit"):
            await kb.search_openwetware(ctx, "q")
        # After 61s the bucket clears.
        fake_now["t"] = 65.0
        await kb.search_openwetware(ctx, "q")


def test_tool_labels_present():
    assert "search_openwetware" in kb.TOOL_LABELS
    assert "fetch_openwetware_protocol" in kb.TOOL_LABELS
    for v in kb.TOOL_LABELS.values():
        assert v.endswith("…")

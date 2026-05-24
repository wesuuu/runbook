"""protocols.io tool wrappers — flags, host check, rate limit, audit, cache."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import rate_limit
from app.services.ai.subagents.protocol_knowledgebase import tools as kb

FIX = Path(__file__).parent.parent / "fixtures" / "protocols_io"
PROTOCOL_URL = "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123"


@dataclass
class _FakeDeps:
    org_id: UUID = field(default_factory=uuid4)
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    external_protocol_cache: dict = field(default_factory=dict)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


def _fake_get_file(json_path: Path):
    payload = json.loads(json_path.read_text())

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, headers=None, timeout=None):
        return _Resp()

    return _get


def _fake_get_dict(payload: dict):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, headers=None, timeout=None):
        return _Resp()

    return _get


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    rate_limit._RECENT_REQUESTS.clear()
    yield
    rate_limit._RECENT_REQUESTS.clear()


@pytest.fixture
def _enabled(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "access_token", "tok-test")
    monkeypatch.setattr(ep.protocols_io, "rate_limit_per_minute", 10)
    yield


@pytest.mark.asyncio
async def test_search_raises_when_master_flag_off(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="not available right now"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_search_raises_when_source_flag_off(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="not available right now"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_search_raises_when_token_missing(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "access_token", "")
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="not available right now"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_fetch_rejects_non_protocols_io_host(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="protocols.io"):
        await kb.fetch_protocols_io(ctx, "https://example.com/view/foo")


@pytest.mark.asyncio
async def test_search_returns_hits_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "search_response.json")
    ):
        result = await kb.search_protocols_io(ctx, "miniprep", limit=3)
    assert result.total == 1
    assert result.hits[0].url == PROTOCOL_URL
    assert ctx.deps.tool_calls[-1]["tool"] == "search_protocols_io"


@pytest.mark.asyncio
async def test_fetch_import_safe_caches_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "protocol_detail.json")
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.import_allowed is True
    assert payload.error is None
    assert PROTOCOL_URL in ctx.deps.external_protocol_cache
    assert ctx.deps.tool_calls[-1]["tool"] == "fetch_protocols_io"


@pytest.mark.asyncio
async def test_fetch_license_restricted_caches_without_steps(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get",
        new=_fake_get_file(FIX / "protocol_detail_nc.json"),
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.import_allowed is False
    assert payload.error is None  # restricted != failure
    assert payload.steps == []
    # A restricted-but-valid payload IS cached (the approval tool re-checks it).
    assert PROTOCOL_URL in ctx.deps.external_protocol_cache
    cached = json.loads(ctx.deps.external_protocol_cache[PROTOCOL_URL])
    assert cached["import_allowed"] is False


@pytest.mark.asyncio
async def test_fetch_genuine_failure_sets_error_and_skips_cache(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get",
        new=_fake_get_dict({"status_code": 1, "error_message": "not found"}),
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.error is not None
    assert PROTOCOL_URL not in ctx.deps.external_protocol_cache


@pytest.mark.asyncio
async def test_rate_limit_trips_after_threshold(_enabled, monkeypatch):
    monkeypatch.setattr(
        settings.features.external_protocols.protocols_io,
        "rate_limit_per_minute",
        2,
    )
    fake_now = {"t": 0.0}
    monkeypatch.setattr(rate_limit, "_now", lambda: fake_now["t"])
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "search_response.json")
    ):
        await kb.search_protocols_io(ctx, "q")
        fake_now["t"] = 1.0
        await kb.search_protocols_io(ctx, "q")
        fake_now["t"] = 2.0
        with pytest.raises(ValueError, match="rate limit"):
            await kb.search_protocols_io(ctx, "q")


def test_tool_labels_present():
    assert "search_protocols_io" in kb.TOOL_LABELS
    assert "fetch_protocols_io" in kb.TOOL_LABELS
    for v in kb.TOOL_LABELS.values():
        assert v.endswith("…")

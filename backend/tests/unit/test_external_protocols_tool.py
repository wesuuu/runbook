"""Approval tool: feature flag gating + audit row + sentinel return string."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.ai.tools.external_protocols import (
    APPROVED_SENTINEL,
    TOOL_LABELS,
    create_protocol_from_external_source,
)


@dataclass
class _FakeDeps:
    org_id: UUID = field(default_factory=uuid4)
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)


@pytest.mark.asyncio
async def test_returns_sentinel_with_payload():
    payload = {
        "title": "X",
        "source_url": "https://openwetware.org/wiki/X",
        "steps": [],
    }
    ctx = _FakeCtx(deps=_FakeDeps())
    result = await create_protocol_from_external_source(
        ctx,
        payload_json=json.dumps(payload),
        title="X",
        source_url="https://openwetware.org/wiki/X",
    )
    assert result.startswith(APPROVED_SENTINEL)
    assert "https://openwetware.org/wiki/X" in result
    assert ctx.deps.tool_calls[-1]["tool"] == "create_protocol_from_external_source"
    assert ctx.deps.tool_calls[-1]["approved"] is True


@pytest.mark.asyncio
async def test_raises_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="disabled"):
        await create_protocol_from_external_source(
            ctx,
            payload_json="{}",
            title="X",
            source_url="https://openwetware.org/wiki/X",
        )


@pytest.mark.asyncio
async def test_rejects_payload_json_that_does_not_parse():
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="payload_json"):
        await create_protocol_from_external_source(
            ctx,
            payload_json="not-json",
            title="X",
            source_url="https://openwetware.org/wiki/X",
        )


def test_label_present():
    assert TOOL_LABELS["create_protocol_from_external_source"].endswith("…")

"""Approval tool: feature flag gating + audit row + sentinel return string.

The approval tool no longer accepts ``payload_json`` from the LLM — the
canonical payload is cached server-side on
``ChatDeps.external_protocol_cache`` (keyed by ``source_url``) and the
tool body looks it up. User-requested deviations also come server-side
on ``ChatDeps.user_deviations`` (computed by the frontend from inline
edits to the approval card), not from LLM-passed args.
"""

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
    external_protocol_cache: dict[str, str] = field(default_factory=dict)
    user_deviations: list[str] = field(default_factory=list)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)


@pytest.mark.asyncio
async def test_returns_sentinel_with_cached_payload_and_project():
    url = "https://openwetware.org/wiki/X"
    payload = {"title": "X", "source_url": url, "steps": []}
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = json.dumps(payload)
    ctx = _FakeCtx(deps=deps)

    result = await create_protocol_from_external_source(
        ctx, source_url=url, title="X", project_name="Cell Culture"
    )

    assert result.startswith(APPROVED_SENTINEL)
    sentinel, project_line, deviations_line, body = result.split("\n", 3)
    assert project_line == "Cell Culture"
    assert json.loads(deviations_line) == []
    assert json.loads(body)["source_url"] == url
    audit = ctx.deps.tool_calls[-1]
    assert audit["tool"] == "create_protocol_from_external_source"
    assert audit["approved"] is True
    assert audit["project_name"] == "Cell Culture"
    assert audit["deviations"] == []


@pytest.mark.asyncio
async def test_threads_user_deviations_from_deps_into_sentinel_and_audit():
    """The frontend computes deviation strings from the user's inline
    edits to the approval card and posts them to /approve, where
    resume_message_streaming stashes them on deps.user_deviations. The
    tool body folds them into the sentinel + audit row."""
    url = "https://openwetware.org/wiki/X"
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = json.dumps({"title": "X", "steps": []})
    deps.user_deviations = [
        "Removed step: spin 5 min",
        "  ",
        "Edited step: ~~heat 60s~~ heat 30s",
    ]
    ctx = _FakeCtx(deps=deps)

    result = await create_protocol_from_external_source(
        ctx, source_url=url, title="X", project_name="Cell Culture"
    )

    sentinel, project_line, deviations_line, _body = result.split("\n", 3)
    assert sentinel == APPROVED_SENTINEL
    assert json.loads(deviations_line) == [
        "Removed step: spin 5 min",
        "Edited step: ~~heat 60s~~ heat 30s",
    ]
    audit = ctx.deps.tool_calls[-1]
    assert audit["deviations"] == [
        "Removed step: spin 5 min",
        "Edited step: ~~heat 60s~~ heat 30s",
    ]


@pytest.mark.asyncio
async def test_raises_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", False)
    deps = _FakeDeps()
    deps.external_protocol_cache["https://openwetware.org/wiki/X"] = "{}"
    ctx = _FakeCtx(deps=deps)
    with pytest.raises(ValueError, match="not available right now"):
        await create_protocol_from_external_source(
            ctx,
            source_url="https://openwetware.org/wiki/X",
            title="X",
            project_name="P",
        )


@pytest.mark.asyncio
async def test_raises_when_payload_not_cached():
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="cache"):
        await create_protocol_from_external_source(
            ctx,
            source_url="https://openwetware.org/wiki/missing",
            title="missing",
            project_name="P",
        )


@pytest.mark.asyncio
async def test_raises_when_project_name_missing():
    """The user must pick a destination project before approval — surfaced
    on the approval card. Blank/whitespace `project_name` is a hard error.
    """
    url = "https://openwetware.org/wiki/X"
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = json.dumps({"title": "X", "steps": []})
    ctx = _FakeCtx(deps=deps)
    with pytest.raises(ValueError, match="project_name"):
        await create_protocol_from_external_source(
            ctx, source_url=url, title="X", project_name="   "
        )


@pytest.mark.asyncio
async def test_raises_when_payload_license_restricted():
    """A cached payload flagged import_allowed=False must be refused —
    re-checked here so a stale cache cannot slip a restricted protocol
    through after the connector already downgraded it."""
    url = "https://www.protocols.io/view/restricted"
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = json.dumps(
        {"title": "X", "steps": [], "import_allowed": False}
    )
    ctx = _FakeCtx(deps=deps)
    with pytest.raises(ValueError, match="license"):
        await create_protocol_from_external_source(
            ctx, source_url=url, title="X", project_name="P"
        )


@pytest.mark.asyncio
async def test_raises_when_cached_payload_is_corrupt():
    """A cache entry that is not valid JSON (corruption, or a non-dict
    value) must fail closed — the license re-check refuses an import it
    cannot verify rather than letting an unparseable payload through."""
    url = "https://www.protocols.io/view/corrupt"
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = "}{ not json"
    ctx = _FakeCtx(deps=deps)
    with pytest.raises(ValueError, match="license"):
        await create_protocol_from_external_source(
            ctx, source_url=url, title="X", project_name="P"
        )


def test_label_present():
    assert TOOL_LABELS["create_protocol_from_external_source"].endswith("…")

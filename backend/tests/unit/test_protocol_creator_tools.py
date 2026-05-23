"""Unit tests for create_protocol tool URL/link fields."""

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.ai.subagents.shared.protocols.tools import (
    CreateProtocolResult,
    ProtocolStepInput,
    create_protocol,
)


def test_create_protocol_result_has_url_fields_with_defaults():
    """Dataclass exposes the new fields with None defaults so older
    construction sites stay safe."""
    result = CreateProtocolResult(
        protocol_id=str(uuid4()),
        protocol_slug="my-protocol",
        protocol_name="My Protocol",
        project_id=str(uuid4()),
    )
    assert result.protocol_url is None
    assert result.protocol_markdown_link is None


async def test_create_protocol_returns_canonical_url_and_markdown_link(
    db_session, test_user, test_org, test_project, monkeypatch
):
    """Happy path: an org-member user creating a protocol gets
    protocol_url = /{org-slug}/protocols/{protocol-slug} and a
    pre-formatted protocol_markdown_link."""
    # Build a fake Protocol that create_protocol_from_spec_service returns.
    fake_protocol = MagicMock()
    fake_protocol.id = uuid4()
    fake_protocol.slug = "buffer-mix-v1"
    fake_protocol.name = "Buffer Mix v1"
    fake_protocol.project_id = test_project.id

    async def fake_service(db, user_id, project_name, spec):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.shared.protocols.tools."
        "create_protocol_from_spec_service",
        fake_service,
    )

    # Stub ChatDeps. db_lock is an async context manager.
    class _NoLock:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    deps = MagicMock()
    deps.db = db_session
    deps.user_id = test_user.id
    deps.org_id = test_org.id
    deps.db_lock = _NoLock()
    deps.tool_calls = []

    ctx = MagicMock()
    ctx.deps = deps

    result = await create_protocol(
        ctx,
        project_name="Test Project",
        protocol_name="Buffer Mix v1",
        protocol_description="…",
        steps=[ProtocolStepInput(name="Step 1", unit_op_name="Mix")],
    )

    # test_org.name slugifies; test_user is a member (fixture default)
    # Canonical form is /{org-slug}/protocols/{protocol-slug} — assert via
    # startswith + endswith pair so the assertion stays robust to future
    # routing changes (e.g. /{org}/library/protocols/{slug}).
    assert result.protocol_url is not None
    assert result.protocol_url.startswith("/")
    assert result.protocol_url.endswith("/protocols/buffer-mix-v1")
    # The first segment is the org slug, which is non-empty.
    assert result.protocol_url.split("/")[1] != ""
    assert result.protocol_markdown_link == f"[Buffer Mix v1]({result.protocol_url})"


async def test_create_protocol_url_none_when_user_not_in_org(
    db_session, test_user, test_project, monkeypatch
):
    """Defensive: a request with an org_id the user is not a member of
    yields protocol_url=None and protocol_markdown_link=None rather
    than a malformed URL."""
    fake_protocol = MagicMock()
    fake_protocol.id = uuid4()
    fake_protocol.slug = "x"
    fake_protocol.name = "X"
    fake_protocol.project_id = test_project.id

    async def fake_service(db, user_id, project_name, spec):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.shared.protocols.tools."
        "create_protocol_from_spec_service",
        fake_service,
    )

    class _NoLock:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    deps = MagicMock()
    deps.db = db_session
    deps.user_id = test_user.id
    deps.org_id = uuid4()  # user is NOT a member of this org
    deps.db_lock = _NoLock()
    deps.tool_calls = []

    ctx = MagicMock()
    ctx.deps = deps

    result = await create_protocol(
        ctx,
        project_name="Test Project",
        protocol_name="X",
        protocol_description="",
        steps=[ProtocolStepInput(name="Step 1", unit_op_name="Mix")],
    )

    assert result.protocol_url is None
    assert result.protocol_markdown_link is None

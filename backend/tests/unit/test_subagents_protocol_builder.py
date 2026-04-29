"""Tests for protocol_builder subagent tools and config."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.protocol_builder import build
from app.services.ai.subagents.protocol_builder.tools import (
    create_protocol, create_unit_op, list_unit_ops,
)


def make_ctx() -> RunContext[ChatDeps]:
    deps = ChatDeps(
        db=AsyncMock(), org_id=uuid.uuid4(),
        user_id=uuid.uuid4(), is_org_admin=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


def test_build_returns_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_builder"
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    assert list_unit_ops in tools
    assert create_unit_op in tools
    assert create_protocol in tools


@pytest.mark.asyncio
async def test_create_unit_op_delegates_to_service(monkeypatch):
    ctx = make_ctx()
    called = {}

    async def fake_service(*args, **kwargs):
        called.update(kwargs)
        op = MagicMock()
        op.id = uuid.uuid4()
        op.name = kwargs["name"]
        op.category = kwargs["category"]
        return op

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.create_unit_op_definition",
        fake_service,
    )
    result = await create_unit_op(
        ctx, name="X", category="C", description="D",
        param_schema={}, scope="org",
    )
    assert called["name"] == "X"
    assert called["scope"] == "org"
    assert result.name == "X"
    assert ctx.deps.tool_calls[-1]["tool"] == "create_unit_op"


@pytest.mark.asyncio
async def test_create_protocol_delegates_to_service(monkeypatch):
    ctx = make_ctx()
    fake_protocol = MagicMock()
    fake_protocol.id = uuid.uuid4()
    fake_protocol.name = "P"
    fake_protocol.project_id = uuid.uuid4()

    async def fake_service(*args, **kwargs):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.create_protocol_from_spec_service",
        fake_service,
    )
    result = await create_protocol(
        ctx, project_name="proj", protocol_name="P",
        protocol_description="D",
        steps_text="Step1 | Op1 | 10",
    )
    assert result.protocol_id == str(fake_protocol.id)
    assert ctx.deps.tool_calls[-1]["tool"] == "create_protocol"

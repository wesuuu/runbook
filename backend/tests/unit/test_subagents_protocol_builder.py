"""Tests for protocol_builder subagent tools and config."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.protocol_builder import build
from app.services.ai.subagents.protocol_builder.tools import (
    ProtocolStepInput, create_protocol, create_unit_op, list_projects,
    list_unit_ops, update_protocol_step, validate_protocol)


def make_ctx() -> RunContext[ChatDeps]:
    deps = ChatDeps(
        db=AsyncMock(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


def test_build_returns_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_builder"
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    assert list_projects in tools
    assert list_unit_ops in tools
    assert create_unit_op in tools
    assert create_protocol in tools
    assert validate_protocol in tools
    assert update_protocol_step in tools


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
        ctx,
        name="X",
        category="C",
        description="D",
        param_schema={},
        scope="org",
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
        ctx,
        project_name="proj",
        protocol_name="P",
        protocol_description="D",
        steps=[
            ProtocolStepInput(
                name="Step1",
                unit_op_name="Op1",
                duration_min=10,
                description="Do step 1",
                category="Media Prep",
            ),
        ],
    )
    assert result.protocol_id == str(fake_protocol.id)
    assert ctx.deps.tool_calls[-1]["tool"] == "create_protocol"
    assert ctx.deps.tool_calls[-1]["steps"] == 1


@pytest.mark.asyncio
async def test_update_protocol_step_delegates_to_service(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake_service(db, user_id, protocol_id, step_index, **kwargs):
        captured.update(
            db=db,
            user_id=user_id,
            protocol_id=protocol_id,
            step_index=step_index,
            **kwargs,
        )
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_protocol_step_service",
        fake_service,
    )

    pid = uuid.uuid4()
    result = await update_protocol_step(
        ctx,
        protocol_id=str(pid),
        step_index=2,
        description="Mix Tris-HCl at 10 mM, pH 7.4",
        category="Buffer Prep",
    )

    assert captured["protocol_id"] == pid
    assert captured["step_index"] == 2
    assert captured["description"] == "Mix Tris-HCl at 10 mM, pH 7.4"
    assert captured["category"] == "Buffer Prep"
    # Untouched fields stayed None
    assert captured["param_schema"] is None
    assert captured["params"] is None
    assert result.fields_updated == ["description", "category"]
    assert ctx.deps.tool_calls[-1]["tool"] == "update_protocol_step"

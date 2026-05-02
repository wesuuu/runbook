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
    from app.services.ai.subagents.protocol_builder.tools import (
        add_protocol_role, add_protocol_step, elevate_unit_op_scope,
        get_protocol, list_protocol_roles, list_protocols,
        remove_protocol_role, remove_protocol_step, replace_step_unit_op,
        reorder_protocol_steps, update_protocol_metadata,
        update_protocol_role, update_unit_op,
    )

    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_builder"
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    expected = {
        list_projects, list_unit_ops, create_unit_op, create_protocol,
        validate_protocol, update_protocol_step,
        # F-0082 additions
        list_protocols, get_protocol, update_protocol_metadata,
        add_protocol_step, remove_protocol_step, reorder_protocol_steps,
        replace_step_unit_op,
        list_protocol_roles, add_protocol_role, update_protocol_role,
        remove_protocol_role,
        update_unit_op, elevate_unit_op_scope,
    }
    assert set(tools) >= expected


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


# ─── F-0082: read tools (Task 10) ─────────────────────────────────────────────


import uuid as _uuid

from app.services.ai.subagents.protocol_builder.tools import (get_protocol,
                                                              list_protocols)


@pytest.mark.asyncio
async def test_list_protocols_tool_delegates(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(*args, **kwargs):
        captured.update(kwargs)
        from app.services.protocols.lookup import ProtocolListItem
        return [
            ProtocolListItem(
                id=_uuid.uuid4(), name="A", description=None,
                project_id=_uuid.uuid4(), project_name="proj", status="DRAFT",
                version_number=0, has_draft=False,
            ),
        ]

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.list_protocols_service",
        fake,
    )
    result = await list_protocols(ctx)
    assert result.total == 1
    assert result.protocols[0].name == "A"
    assert ctx.deps.tool_calls[-1]["tool"] == "list_protocols"


@pytest.mark.asyncio
async def test_get_protocol_tool_delegates(monkeypatch):
    ctx = make_ctx()
    pid = _uuid.uuid4()

    async def fake(*args, **kwargs):
        from app.services.protocols.lookup import ProtocolFull
        return ProtocolFull(
            id=pid, name="P", description="d",
            project_id=_uuid.uuid4(), project_name="proj",
            status="DRAFT", version_number=0, has_draft=False,
            graph={"nodes": [], "edges": []}, roles=[],
        )

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.get_protocol_full_service",
        fake,
    )
    result = await get_protocol(ctx, protocol_id=str(pid))
    assert result.protocol_id == str(pid)
    assert result.summary.startswith("Protocol 'P'")
    assert ctx.deps.tool_calls[-1]["tool"] == "get_protocol"


@pytest.mark.asyncio
async def test_get_protocol_tool_returns_error_on_value_error(monkeypatch):
    ctx = make_ctx()

    async def fake(*args, **kwargs):
        raise ValueError("Protocol not found")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.get_protocol_full_service",
        fake,
    )
    result = await get_protocol(ctx, protocol_id=str(_uuid.uuid4()))
    assert result.ok is False
    assert "not found" in result.summary


# ─── F-0082: mutation tools — metadata + graph (Task 11) ──────────────────────


from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_step, remove_protocol_step, reorder_protocol_steps,
    replace_step_unit_op, update_protocol_metadata)


@pytest.mark.asyncio
async def test_update_protocol_metadata_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.name = kwargs.get("name") or "old"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_protocol_metadata_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await update_protocol_metadata(
        ctx, protocol_id=str(pid), name="New Name",
    )
    assert captured["protocol_id"] == pid
    assert captured["name"] == "New Name"
    assert result.ok is True
    assert ctx.deps.tool_calls[-1]["tool"] == "update_protocol_metadata"


@pytest.mark.asyncio
async def test_update_protocol_metadata_published_returns_error(monkeypatch):
    ctx = make_ctx()

    async def fake(db, **kwargs):
        raise ValueError("Protocol is published — create a draft first.")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_protocol_metadata_service",
        fake,
    )
    result = await update_protocol_metadata(
        ctx, protocol_id=str(_uuid.uuid4()), name="X",
    )
    assert result.ok is False
    assert "published" in result.summary


@pytest.mark.asyncio
async def test_add_protocol_step_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.add_step_service",
        fake,
    )
    pid = _uuid.uuid4()
    rid = _uuid.uuid4()
    result = await add_protocol_step(
        ctx, protocol_id=str(pid), name="Mix", unit_op_name="Mix Op",
        duration_min=20, role_id=str(rid),
    )
    assert captured["protocol_id"] == pid
    assert captured["role_id"] == rid
    assert result.ok is True


@pytest.mark.asyncio
async def test_remove_protocol_step_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.remove_step_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await remove_protocol_step(
        ctx, protocol_id=str(pid), step_index=2,
    )
    assert captured["step_index"] == 2
    assert result.ok is True


@pytest.mark.asyncio
async def test_reorder_protocol_steps_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.reorder_steps_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await reorder_protocol_steps(
        ctx, protocol_id=str(pid), ordered_step_indices=[2, 0, 1],
    )
    assert captured["ordered_step_indices"] == [2, 0, 1]
    assert result.ok is True


@pytest.mark.asyncio
async def test_replace_step_unit_op_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.replace_step_unit_op_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await replace_step_unit_op(
        ctx, protocol_id=str(pid), step_index=1, new_unit_op_name="Cell Seeding",
    )
    assert captured["new_unit_op_name"] == "Cell Seeding"
    assert result.ok is True


# ─── F-0082: role tools (Task 12) ─────────────────────────────────────────────


from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_role, list_protocol_roles, remove_protocol_role,
    update_protocol_role)


@pytest.mark.asyncio
async def test_list_protocol_roles_tool(monkeypatch):
    ctx = make_ctx()

    async def fake(db, **kwargs):
        from app.models.science import ProtocolRole
        r1 = ProtocolRole(name="Op", color="#fff", sort_order=0)
        r1.id = _uuid.uuid4()
        return [r1]

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.list_roles_service",
        fake,
    )
    result = await list_protocol_roles(ctx, protocol_id=str(_uuid.uuid4()))
    assert result.ok is True
    assert result.roles[0].name == "Op"


@pytest.mark.asyncio
async def test_add_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        from app.models.science import ProtocolRole
        r = ProtocolRole(name=kwargs["name"], color="#fff", sort_order=0)
        r.id = _uuid.uuid4()
        return r

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.add_role_service",
        fake,
    )
    result = await add_protocol_role(
        ctx, protocol_id=str(_uuid.uuid4()), name="Operator",
    )
    assert captured["name"] == "Operator"
    assert result.ok is True


@pytest.mark.asyncio
async def test_update_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        from app.models.science import ProtocolRole
        r = ProtocolRole(name=kwargs.get("name") or "X", color="#fff",
                         sort_order=0)
        r.id = kwargs["role_id"]
        return r

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_role_service",
        fake,
    )
    rid = _uuid.uuid4()
    result = await update_protocol_role(ctx, role_id=str(rid), name="New")
    assert captured["role_id"] == rid
    assert captured["name"] == "New"
    assert result.ok is True


@pytest.mark.asyncio
async def test_remove_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.remove_role_service",
        fake,
    )
    rid = _uuid.uuid4()
    result = await remove_protocol_role(ctx, role_id=str(rid))
    assert captured["role_id"] == rid
    assert result.ok is True


# ─── F-0082: unit op tools — update + elevate (Task 13) ───────────────────────


from app.services.ai.subagents.protocol_builder.tools import (
    elevate_unit_op_scope, update_unit_op)


@pytest.mark.asyncio
async def test_update_unit_op_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.id = kwargs["unit_op_id"]
        m.name = kwargs.get("name") or "Old"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_unit_op_definition_service",
        fake,
    )
    uoid = _uuid.uuid4()
    result = await update_unit_op(
        ctx, unit_op_id=str(uoid), description="new desc",
    )
    assert captured["unit_op_id"] == uoid
    assert captured["description"] == "new desc"
    assert captured["is_org_admin"] is False  # from ChatDeps
    assert result.ok is True


@pytest.mark.asyncio
async def test_elevate_unit_op_scope_tool(monkeypatch):
    ctx = make_ctx()
    ctx.deps.is_org_admin = True
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.id = kwargs["unit_op_id"]
        m.name = "X"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.elevate_unit_op_scope_service",
        fake,
    )
    uoid = _uuid.uuid4()
    result = await elevate_unit_op_scope(ctx, unit_op_id=str(uoid))
    assert captured["unit_op_id"] == uoid
    assert captured["is_org_admin"] is True
    assert result.ok is True


@pytest.mark.asyncio
async def test_elevate_returns_error_when_not_admin(monkeypatch):
    ctx = make_ctx()  # is_org_admin defaults False

    async def fake(db, **kwargs):
        raise ValueError("Only organization admins can elevate unit ops.")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.elevate_unit_op_scope_service",
        fake,
    )
    result = await elevate_unit_op_scope(ctx, unit_op_id=str(_uuid.uuid4()))
    assert result.ok is False
    assert "admin" in result.summary

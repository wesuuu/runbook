"""Tools for the protocol_builder subagent.

Thin wrappers over the protocol creation and unit_ops services.
No business logic lives here — only argument mapping, service delegation,
and tool_calls audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps
from app.services.protocols.creation import ProtocolSpec, ProtocolStep
from app.services.protocols.creation import \
    create_protocol_from_spec as create_protocol_from_spec_service
from app.services.protocols.unit_ops import create_unit_op_definition

logger = logging.getLogger(__name__)

# ─── Result Models ─────────────────────────────────────────────────────────────


@dataclass
class UnitOpItem:
    """Summary of a single unit op definition."""

    id: UUID
    name: str
    category: str
    description: str | None


@dataclass
class ListUnitOpsResult:
    """Result of a list_unit_ops call."""

    total: int
    unit_ops: list[UnitOpItem]
    message: str = ""


@dataclass
class CreateUnitOpResult:
    """Result of a create_unit_op call."""

    id: UUID
    name: str
    category: str


@dataclass
class CreateProtocolResult:
    """Result of a create_protocol call."""

    protocol_id: str
    protocol_name: str
    project_id: str


# ─── Tools ─────────────────────────────────────────────────────────────────────


async def list_unit_ops(ctx: RunContext[ChatDeps]) -> ListUnitOpsResult:
    """List unit op definitions available to this org (org-scoped + global).

    Use this to discover what unit op names exist before building protocol
    steps. Do NOT show this list verbatim to the user.

    Args:
        ctx: Run context with shared deps.
    """
    from sqlalchemy import or_, select

    from app.models.science import UnitOpDefinition

    result = await ctx.deps.db.execute(
        select(UnitOpDefinition)
        .where(
            or_(
                UnitOpDefinition.organization_id == ctx.deps.org_id,
                UnitOpDefinition.organization_id.is_(None),
            )
        )
        .order_by(UnitOpDefinition.category, UnitOpDefinition.name)
    )
    ops = list(result.scalars().all())

    ctx.deps.tool_calls.append(
        {
            "tool": "list_unit_ops",
            "subagent": "protocol_builder",
            "results": len(ops),
        }
    )

    if not ops:
        return ListUnitOpsResult(
            total=0,
            unit_ops=[],
            message="No unit op definitions found for this organisation.",
        )

    return ListUnitOpsResult(
        total=len(ops),
        unit_ops=[
            UnitOpItem(
                id=op.id,
                name=op.name,
                category=op.category,
                description=op.description,
            )
            for op in ops
        ],
    )


async def create_unit_op(
    ctx: RunContext[ChatDeps],
    name: str,
    category: str,
    description: str,
    param_schema: dict[str, Any],
    scope: str = "project",
    project_id: UUID | None = None,
) -> CreateUnitOpResult:
    """Create a new unit op definition in the org or project catalog.

    Args:
        ctx: Run context with shared deps.
        name: Display name for the unit op (must be unique within scope).
        category: Category label (e.g. "Cell Culture", "Reaction").
        description: Human-readable description of what this operation does.
        param_schema: JSON Schema dict describing the operation's parameters.
        scope: ``"org"`` (org-admin only) or ``"project"``.
        project_id: Required when scope is ``"project"``.
    """
    op = await create_unit_op_definition(
        ctx.deps.db,
        user_id=ctx.deps.user_id,
        org_id=ctx.deps.org_id,
        is_org_admin=ctx.deps.is_org_admin,
        scope=scope,
        name=name,
        category=category,
        description=description,
        param_schema=param_schema,
        project_id=project_id,
    )

    ctx.deps.tool_calls.append(
        {
            "tool": "create_unit_op",
            "subagent": "protocol_builder",
            "name": name,
            "scope": scope,
        }
    )

    return CreateUnitOpResult(id=op.id, name=op.name, category=op.category)


async def create_protocol(
    ctx: RunContext[ChatDeps],
    project_name: str,
    protocol_name: str,
    protocol_description: str,
    steps_text: str,
) -> CreateProtocolResult:
    """Create a DRAFT Protocol in the named project from a pipe-delimited step list.

    ``steps_text`` format — one step per line::

        step_name | unit_op_name | duration_min

    Lines starting with ``#`` and blank lines are skipped.
    ``duration_min`` defaults to 30 if missing or non-numeric.

    Args:
        ctx: Run context with shared deps.
        project_name: Partial or full project name (case-insensitive match).
        protocol_name: Name for the new protocol record.
        protocol_description: Brief description of the protocol's purpose.
        steps_text: Pipe-delimited step definitions (one per line).
    """
    steps: list[ProtocolStep] = []
    for raw_line in steps_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        step_name = parts[0] if len(parts) > 0 else ""
        unit_op_name = parts[1] if len(parts) > 1 else step_name
        try:
            duration_min = int(parts[2]) if len(parts) > 2 else 30
        except (ValueError, IndexError):
            duration_min = 30
        if not step_name:
            continue
        steps.append(
            ProtocolStep(
                name=step_name,
                unit_op_name=unit_op_name,
                duration_min=duration_min,
            )
        )

    spec = ProtocolSpec(
        name=protocol_name,
        description=protocol_description,
        steps=steps,
    )

    protocol = await create_protocol_from_spec_service(
        ctx.deps.db,
        ctx.deps.user_id,
        project_name,
        spec,
    )

    ctx.deps.tool_calls.append(
        {
            "tool": "create_protocol",
            "subagent": "protocol_builder",
            "protocol_name": protocol_name,
            "project_name": project_name,
            "steps": len(steps),
        }
    )

    return CreateProtocolResult(
        protocol_id=str(protocol.id),
        protocol_name=protocol.name,
        project_id=str(protocol.project_id),
    )

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
from sqlalchemy import select

from app.models.science import Project, Protocol, UnitOpDefinition
from app.services.ai.deps import ChatDeps
from app.services.protocols.creation import ProtocolSpec, ProtocolStep
from app.services.protocols.creation import \
    create_protocol_from_spec as create_protocol_from_spec_service
from app.services.protocols.creation import \
    update_protocol_step as update_protocol_step_service
from app.services.protocols.unit_ops import create_unit_op_definition
from app.services.protocols.validation import (ValidationIssue,
                                               validate_protocol_graph)

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


@dataclass
class ProtocolStepInput:
    """Structured step definition for ``create_protocol``.

    All fields except ``name``/``unit_op_name`` are optional but should be
    populated whenever the agent has the information. Empty strings here
    surface as validation warnings later.
    """

    name: str
    unit_op_name: str
    duration_min: int = 30
    description: str = ""
    category: str = ""
    params: dict[str, Any] | None = None


async def create_protocol(
    ctx: RunContext[ChatDeps],
    project_name: str,
    protocol_name: str,
    protocol_description: str,
    steps: list[ProtocolStepInput],
) -> CreateProtocolResult:
    """Create a DRAFT Protocol in the named project from a structured step list.

    Each step carries name, unit_op_name (matched against the catalog),
    duration_min, description, category, and any params. Per-step
    description and category override what's looked up from the catalog;
    leave them blank only when the matched unit op already supplies them.

    Args:
        ctx: Run context with shared deps.
        project_name: Partial or full project name (case-insensitive match).
        protocol_name: Name for the new protocol record.
        protocol_description: Brief description of the protocol's purpose.
        steps: Structured step list (one entry per protocol step).
    """
    spec_steps: list[ProtocolStep] = []
    for s in steps:
        if not s.name:
            continue
        spec_steps.append(
            ProtocolStep(
                name=s.name,
                unit_op_name=s.unit_op_name or s.name,
                duration_min=s.duration_min,
                description=s.description,
                category=s.category or "General",
                params=s.params or {},
            )
        )

    spec = ProtocolSpec(
        name=protocol_name,
        description=protocol_description,
        steps=spec_steps,
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
            "protocol_id": str(protocol.id),
            "protocol_name": protocol_name,
            "project_id": str(protocol.project_id),
            "project_name": project_name,
            "steps": len(spec_steps),
        }
    )

    return CreateProtocolResult(
        protocol_id=str(protocol.id),
        protocol_name=protocol.name,
        project_id=str(protocol.project_id),
    )


@dataclass
class ValidateProtocolResult:
    """Result of a validate_protocol call."""

    ok: bool
    error_count: int
    warning_count: int
    issues: list[ValidationIssue]
    summary: str


async def validate_protocol(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
) -> ValidateProtocolResult:
    """Check a protocol for structural and quality problems.

    Run this after `create_protocol` to surface missing Process Start nodes,
    unit ops with no parameter schema, hollow custom ops, and orphan steps.
    Errors block usability; warnings flag rough spots a scientist will hit.
    """
    proto_row = await ctx.deps.db.execute(
        select(Protocol).where(Protocol.id == UUID(protocol_id))
    )
    protocol = proto_row.scalar_one_or_none()
    if protocol is None:
        return ValidateProtocolResult(
            ok=False,
            error_count=1,
            warning_count=0,
            issues=[
                ValidationIssue(
                    severity="error",
                    code="protocol_not_found",
                    message=f"Protocol {protocol_id} not found.",
                )
            ],
            summary=f"Protocol {protocol_id} not found.",
        )

    unit_ops_q = await ctx.deps.db.execute(
        select(UnitOpDefinition).where(
            (UnitOpDefinition.organization_id == ctx.deps.org_id)
            | (UnitOpDefinition.organization_id.is_(None))
        )
    )
    unit_ops = list(unit_ops_q.scalars().all())

    result = validate_protocol_graph(protocol.graph or {}, unit_ops)
    error_count = sum(1 for i in result.issues if i.severity == "error")
    warning_count = sum(1 for i in result.issues if i.severity == "warning")

    if result.ok and not result.issues:
        summary = "Protocol passes all checks."
    elif result.ok:
        summary = f"Protocol is valid with {warning_count} warning(s)."
    else:
        summary = f"Protocol has {error_count} error(s) and {warning_count} warning(s)."

    ctx.deps.tool_calls.append(
        {
            "tool": "validate_protocol",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "errors": error_count,
            "warnings": warning_count,
        }
    )

    return ValidateProtocolResult(
        ok=result.ok,
        error_count=error_count,
        warning_count=warning_count,
        issues=result.issues,
        summary=summary,
    )


@dataclass
class ProjectItem:
    """Summary of a single project the user has access to."""

    id: str
    name: str
    description: str | None


@dataclass
class ListProjectsResult:
    """Result of a list_projects call."""

    total: int
    projects: list[ProjectItem]
    message: str = ""


async def list_projects(ctx: RunContext[ChatDeps]) -> ListProjectsResult:
    """List projects the current user has access to in their org.

    Use this when the user wants to create a protocol but hasn't named a
    project yet, or when an attempted `create_protocol` failed because the
    project name didn't resolve. Pick the closest match by name and confirm
    with the user before retrying — don't fabricate a project that isn't
    in the list.

    Args:
        ctx: Run context with shared deps.
    """
    result = await ctx.deps.db.execute(
        select(Project)
        .where(Project.organization_id == ctx.deps.org_id)
        .order_by(Project.name)
    )
    projects = list(result.scalars().all())

    ctx.deps.tool_calls.append(
        {
            "tool": "list_projects",
            "subagent": "protocol_builder",
            "results": len(projects),
        }
    )

    if not projects:
        return ListProjectsResult(
            total=0,
            projects=[],
            message=(
                "No projects exist in this organisation yet. Ask the user "
                "to create one in the Projects tab before drafting a "
                "protocol."
            ),
        )

    return ListProjectsResult(
        total=len(projects),
        projects=[
            ProjectItem(
                id=str(p.id),
                name=p.name,
                description=p.description,
            )
            for p in projects
        ],
    )


@dataclass
class UpdateProtocolStepResult:
    """Result of an update_protocol_step call."""

    protocol_id: str
    step_index: int
    fields_updated: list[str]


async def update_protocol_step(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    step_index: int,
    description: str | None = None,
    category: str | None = None,
    param_schema: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> UpdateProtocolStepResult:
    """Patch one unit-op step in an existing protocol's graph.

    Use after `validate_protocol` flags fixable issues — fill in a missing
    description, replace a placeholder category, or add a non-empty
    paramSchema. ``step_index`` is the 0-based index of the unit-op node
    among unit-op nodes only (the Process Start is excluded). Only the
    arguments you pass are written; everything else is left as-is.

    Args:
        ctx: Run context with shared deps.
        protocol_id: UUID of the protocol to patch.
        step_index: 0-based unit-op-step index to patch.
        description: New step description (or None to leave alone).
        category: New step category (or None to leave alone).
        param_schema: New JSON Schema dict (or None to leave alone).
        params: New default param values (or None to leave alone).
    """
    fields_updated: list[str] = []
    if description is not None:
        fields_updated.append("description")
    if category is not None:
        fields_updated.append("category")
    if param_schema is not None:
        fields_updated.append("param_schema")
    if params is not None:
        fields_updated.append("params")

    await update_protocol_step_service(
        ctx.deps.db,
        ctx.deps.user_id,
        UUID(protocol_id),
        step_index,
        description=description,
        category=category,
        param_schema=param_schema,
        params=params,
    )

    ctx.deps.tool_calls.append(
        {
            "tool": "update_protocol_step",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "step_index": step_index,
            "fields_updated": fields_updated,
        }
    )

    return UpdateProtocolStepResult(
        protocol_id=protocol_id,
        step_index=step_index,
        fields_updated=fields_updated,
    )

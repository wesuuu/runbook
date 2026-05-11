"""Protocol-building tool functions shared by protocol_creator + protocol_editor.

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

from app.models.science import Project, Protocol, ProtocolRole, UnitOpDefinition
from app.services.ai.deps import ChatDeps
from app.services.protocols.creation import ProtocolSpec, ProtocolStep
from app.services.protocols.creation import \
    create_protocol_from_spec as create_protocol_from_spec_service
from app.services.protocols.creation import \
    update_protocol_metadata as update_protocol_metadata_service
from app.services.protocols.creation import \
    update_protocol_step as update_protocol_step_service
from app.services.protocols.graph import add_step as add_step_service
from app.services.protocols.graph import remove_step as remove_step_service
from app.services.protocols.graph import reorder_steps as reorder_steps_service
from app.services.protocols.graph import \
    replace_step_unit_op as replace_step_unit_op_service
from app.services.protocols.lookup import ProtocolFull
from app.services.protocols.lookup import \
    get_protocol_full as get_protocol_full_service
from app.services.protocols.lookup import \
    list_protocols as list_protocols_service
from app.services.protocols.roles import add_role as add_role_service
from app.services.protocols.roles import list_roles as list_roles_service
from app.services.protocols.roles import remove_role as remove_role_service
from app.services.protocols.roles import update_role as update_role_service
from app.services.protocols.unit_ops import create_unit_op_definition
from app.services.protocols.unit_ops import \
    elevate_unit_op_scope as elevate_unit_op_scope_service
from app.services.protocols.unit_ops import \
    update_unit_op_definition as update_unit_op_definition_service
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
    try:
        full = await get_protocol_full_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=UUID(protocol_id),
        )
    except ValueError as e:
        return ValidateProtocolResult(
            ok=False,
            error_count=1,
            warning_count=0,
            issues=[
                ValidationIssue(
                    severity="error",
                    code="protocol_not_found",
                    message=str(e),
                )
            ],
            summary=str(e),
        )

    unit_ops_q = await ctx.deps.db.execute(
        select(UnitOpDefinition).where(
            (UnitOpDefinition.organization_id == ctx.deps.org_id)
            | (UnitOpDefinition.organization_id.is_(None))
        )
    )
    unit_ops = list(unit_ops_q.scalars().all())

    roles_q = await ctx.deps.db.execute(
        select(ProtocolRole).where(ProtocolRole.protocol_id == full.id)
    )
    roles = list(roles_q.scalars().all())

    result = validate_protocol_graph(full.graph or {}, unit_ops, roles=roles)
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
    role_id: str | None = None,
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
    if role_id is not None:
        fields_updated.append("role_id")

    await update_protocol_step_service(
        ctx.deps.db,
        ctx.deps.user_id,
        UUID(protocol_id),
        step_index,
        description=description,
        category=category,
        param_schema=param_schema,
        params=params,
        role_id=UUID(role_id) if role_id else None,
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


# ─── list_protocols / get_protocol ─────────────────────────────────────────────


@dataclass
class ProtocolSummary:
    id: str
    name: str
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool


@dataclass
class ListProtocolsResult:
    ok: bool
    total: int
    protocols: list[ProtocolSummary]
    summary: str


@dataclass
class RoleSummary:
    id: str
    name: str
    sort_order: int


@dataclass
class GetProtocolResult:
    ok: bool
    protocol_id: str
    name: str
    description: str | None
    status: str
    version_number: int
    has_draft: bool
    step_count: int
    roles: list[RoleSummary]
    graph: dict[str, Any]
    summary: str


def _summary_from_full(p: ProtocolFull) -> str:
    state = p.status
    if p.has_draft:
        state += " (draft pending)"
    step_count = len([n for n in p.graph.get("nodes", []) if n.get("type") == "unitOp"])
    return (
        f"Protocol '{p.name}' in project '{p.project_name}' — {state}, "
        f"v{p.version_number}, {step_count} steps"
    )


async def list_protocols(
    ctx: RunContext[ChatDeps],
    project_id: str | None = None,
) -> ListProtocolsResult:
    """List protocols the user can see. Optionally scope to one project.

    Args:
        ctx: Run context with shared deps.
        project_id: Optional project UUID string to filter to one project.
    """
    proj_uuid = UUID(project_id) if project_id else None
    items = await list_protocols_service(
        ctx.deps.db,
        user_id=ctx.deps.user_id,
        org_id=ctx.deps.org_id,
        project_id=proj_uuid,
    )
    ctx.deps.tool_calls.append(
        {
            "tool": "list_protocols",
            "subagent": "protocol_builder",
            "results": len(items),
        }
    )
    return ListProtocolsResult(
        ok=True,
        total=len(items),
        protocols=[
            ProtocolSummary(
                id=str(it.id),
                name=it.name,
                project_name=it.project_name,
                status=it.status,
                version_number=it.version_number,
                has_draft=it.has_draft,
            )
            for it in items
        ],
        summary=f"Found {len(items)} protocol(s).",
    )


async def get_protocol(
    ctx: RunContext[ChatDeps], protocol_id: str
) -> GetProtocolResult:
    """Return full state of one protocol (metadata, graph, roles).

    Args:
        ctx: Run context with shared deps.
        protocol_id: UUID string of the protocol to fetch.
    """
    try:
        full = await get_protocol_full_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=UUID(protocol_id),
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "get_protocol",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return GetProtocolResult(
            ok=False,
            protocol_id=protocol_id,
            name="",
            description=None,
            status="",
            version_number=0,
            has_draft=False,
            step_count=0,
            roles=[],
            graph={},
            summary=str(e),
        )
    ctx.deps.tool_calls.append(
        {
            "tool": "get_protocol",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
        }
    )
    step_count = len(
        [n for n in full.graph.get("nodes", []) if n.get("type") == "unitOp"]
    )
    return GetProtocolResult(
        ok=True,
        protocol_id=str(full.id),
        name=full.name,
        description=full.description,
        status=full.status,
        version_number=full.version_number,
        has_draft=full.has_draft,
        step_count=step_count,
        roles=[
            RoleSummary(id=str(r.id), name=r.name, sort_order=r.sort_order)
            for r in full.roles
        ],
        graph=full.graph,
        summary=_summary_from_full(full),
    )


# ─── Mutation tools (DRAFT-only) ───────────────────────────────────────────────


@dataclass
class ProtocolMutationResult:
    ok: bool
    protocol_id: str
    summary: str


def _mutation_error(protocol_id: str, exc: ValueError) -> ProtocolMutationResult:
    return ProtocolMutationResult(ok=False, protocol_id=protocol_id, summary=str(exc))


@dataclass
class CreateDraftResult:
    """Result of a create_draft call."""

    ok: bool
    protocol_id: str
    draft_version_number: int
    created: bool
    summary: str


async def create_draft(
    ctx: RunContext[ChatDeps], protocol_id: str
) -> CreateDraftResult:
    """Open a draft on an APPROVED protocol so edits can land.

    The other mutation tools refuse on APPROVED protocols with a message
    pointing here. Call this once when you hit that error, then re-issue
    your edits — they will write to the draft version. Idempotent: if a
    draft already exists, this returns it without creating a new one.
    The user later publishes via the protocol editor's UI (no chat tool
    for publish yet).
    """
    from app.services.protocols.draft import create_draft_version

    pid = UUID(protocol_id)
    try:
        draft, created = await create_draft_version(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "create_draft",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return CreateDraftResult(
            ok=False,
            protocol_id=protocol_id,
            draft_version_number=0,
            created=False,
            summary=str(e),
        )
    ctx.deps.tool_calls.append(
        {
            "tool": "create_draft",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "draft_version_number": draft.version_number,
            "created": created,
        }
    )
    summary = (
        f"Opened draft version {draft.version_number}. Re-issue your edits — "
        "they will now apply to the draft."
        if created
        else (
            f"Draft version {draft.version_number} already open. Continue "
            "editing it."
        )
    )
    return CreateDraftResult(
        ok=True,
        protocol_id=protocol_id,
        draft_version_number=draft.version_number,
        created=created,
        summary=summary,
    )


async def update_protocol_metadata(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str | None = None,
    description: str | None = None,
) -> ProtocolMutationResult:
    """Patch a DRAFT protocol's name and/or description."""
    pid = UUID(protocol_id)
    try:
        await update_protocol_metadata_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            name=name,
            description=description,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "update_protocol_metadata",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _mutation_error(protocol_id, e)
    fields = [
        k for k, v in (("name", name), ("description", description)) if v is not None
    ]
    ctx.deps.tool_calls.append(
        {
            "tool": "update_protocol_metadata",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "fields_updated": fields,
        }
    )
    return ProtocolMutationResult(
        ok=True,
        protocol_id=protocol_id,
        summary=f"Updated {', '.join(fields)} on protocol.",
    )


async def add_protocol_step(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str,
    unit_op_name: str,
    duration_min: int = 30,
    description: str = "",
    category: str = "General",
    params: dict[str, Any] | None = None,
    after_step_index: int | None = None,
    role_id: str | None = None,
) -> ProtocolMutationResult:
    """Append or insert a unit-op step into a DRAFT protocol's graph."""
    pid = UUID(protocol_id)
    rid = UUID(role_id) if role_id else None
    try:
        await add_step_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            name=name,
            unit_op_name=unit_op_name,
            duration_min=duration_min,
            description=description,
            category=category,
            params=params,
            after_step_index=after_step_index,
            role_id=rid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "add_protocol_step",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _mutation_error(protocol_id, e)
    where = (
        f"after step {after_step_index}" if after_step_index is not None else "appended"
    )
    ctx.deps.tool_calls.append(
        {
            "tool": "add_protocol_step",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "name": name,
        }
    )
    return ProtocolMutationResult(
        ok=True,
        protocol_id=protocol_id,
        summary=f"Added step '{name}' ({where}).",
    )


async def remove_protocol_step(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    step_index: int,
) -> ProtocolMutationResult:
    """Delete the unit-op step at the given 0-based index."""
    pid = UUID(protocol_id)
    try:
        await remove_step_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            step_index=step_index,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "remove_protocol_step",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append(
        {
            "tool": "remove_protocol_step",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "step_index": step_index,
        }
    )
    return ProtocolMutationResult(
        ok=True,
        protocol_id=protocol_id,
        summary=f"Removed step {step_index}.",
    )


async def reorder_protocol_steps(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    ordered_step_indices: list[int],
) -> ProtocolMutationResult:
    """Reorder unit-op steps. Pass a permutation of 0..N-1."""
    pid = UUID(protocol_id)
    try:
        await reorder_steps_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            ordered_step_indices=ordered_step_indices,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "reorder_protocol_steps",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append(
        {
            "tool": "reorder_protocol_steps",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "order": ordered_step_indices,
        }
    )
    return ProtocolMutationResult(
        ok=True,
        protocol_id=protocol_id,
        summary=f"Reordered steps to {ordered_step_indices}.",
    )


async def replace_step_unit_op(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    step_index: int,
    new_unit_op_name: str,
) -> ProtocolMutationResult:
    """Swap the underlying unit op for an existing step. Label is preserved."""
    pid = UUID(protocol_id)
    try:
        await replace_step_unit_op_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            step_index=step_index,
            new_unit_op_name=new_unit_op_name,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "replace_step_unit_op",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append(
        {
            "tool": "replace_step_unit_op",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "step_index": step_index,
            "new_unit_op_name": new_unit_op_name,
        }
    )
    return ProtocolMutationResult(
        ok=True,
        protocol_id=protocol_id,
        summary=f"Replaced step {step_index} unit op with '{new_unit_op_name}'.",
    )


# ─── Role tools ────────────────────────────────────────────────────────────────


@dataclass
class RoleItem:
    id: str
    name: str
    color: str
    sort_order: int


@dataclass
class ListRolesResult:
    ok: bool
    total: int
    roles: list[RoleItem]
    summary: str


@dataclass
class RoleMutationResult:
    ok: bool
    role_id: str
    summary: str


def _role_error(role_id: str, exc: ValueError) -> RoleMutationResult:
    return RoleMutationResult(ok=False, role_id=role_id, summary=str(exc))


async def list_protocol_roles(
    ctx: RunContext[ChatDeps], protocol_id: str
) -> ListRolesResult:
    """List roles on the given protocol, sorted by sort_order."""
    pid = UUID(protocol_id)
    try:
        roles = await list_roles_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "list_protocol_roles",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return ListRolesResult(ok=False, total=0, roles=[], summary=str(e))
    ctx.deps.tool_calls.append(
        {
            "tool": "list_protocol_roles",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "results": len(roles),
        }
    )
    return ListRolesResult(
        ok=True,
        total=len(roles),
        roles=[
            RoleItem(
                id=str(r.id),
                name=r.name,
                color=r.color,
                sort_order=r.sort_order,
            )
            for r in roles
        ],
        summary=f"Found {len(roles)} role(s) on protocol.",
    )


async def add_protocol_role(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str,
    color: str = "#94a3b8",
    sort_order: int | None = None,
) -> RoleMutationResult:
    """Add a new role to a DRAFT protocol."""
    pid = UUID(protocol_id)
    try:
        role = await add_role_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            protocol_id=pid,
            name=name,
            color=color,
            sort_order=sort_order,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "add_protocol_role",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return RoleMutationResult(ok=False, role_id="", summary=str(e))
    ctx.deps.tool_calls.append(
        {
            "tool": "add_protocol_role",
            "subagent": "protocol_builder",
            "protocol_id": protocol_id,
            "role_id": str(role.id),
        }
    )
    return RoleMutationResult(
        ok=True,
        role_id=str(role.id),
        summary=f"Added role '{name}'.",
    )


async def update_protocol_role(
    ctx: RunContext[ChatDeps],
    role_id: str,
    name: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
) -> RoleMutationResult:
    """Patch a role's name, color, or sort_order on a DRAFT protocol."""
    rid = UUID(role_id)
    try:
        await update_role_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            role_id=rid,
            name=name,
            color=color,
            sort_order=sort_order,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "update_protocol_role",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _role_error(role_id, e)
    fields = [
        k
        for k, v in (
            ("name", name),
            ("color", color),
            ("sort_order", sort_order),
        )
        if v is not None
    ]
    ctx.deps.tool_calls.append(
        {
            "tool": "update_protocol_role",
            "subagent": "protocol_builder",
            "role_id": role_id,
            "fields_updated": fields,
        }
    )
    return RoleMutationResult(
        ok=True,
        role_id=role_id,
        summary=f"Updated role ({', '.join(fields)}).",
    )


async def remove_protocol_role(
    ctx: RunContext[ChatDeps], role_id: str
) -> RoleMutationResult:
    """Remove a role from a DRAFT protocol."""
    rid = UUID(role_id)
    try:
        await remove_role_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            role_id=rid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "remove_protocol_role",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _role_error(role_id, e)
    ctx.deps.tool_calls.append(
        {
            "tool": "remove_protocol_role",
            "subagent": "protocol_builder",
            "role_id": role_id,
        }
    )
    return RoleMutationResult(
        ok=True,
        role_id=role_id,
        summary="Removed role.",
    )


# ─── Unit op tools (update + elevate) ──────────────────────────────────────────


@dataclass
class UnitOpMutationResult:
    ok: bool
    unit_op_id: str
    name: str
    summary: str


def _uo_error(unit_op_id: str, exc: ValueError) -> UnitOpMutationResult:
    return UnitOpMutationResult(
        ok=False,
        unit_op_id=unit_op_id,
        name="",
        summary=str(exc),
    )


async def update_unit_op(
    ctx: RunContext[ChatDeps],
    unit_op_id: str,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    param_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpMutationResult:
    """Patch an existing unit op definition.

    Org-scoped ops require org-admin (resolved from ChatDeps.is_org_admin).
    Library-override rows are refused.
    """
    uoid = UUID(unit_op_id)
    try:
        op = await update_unit_op_definition_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            org_id=ctx.deps.org_id,
            is_org_admin=ctx.deps.is_org_admin,
            unit_op_id=uoid,
            name=name,
            category=category,
            description=description,
            param_schema=param_schema,
            result_schema=result_schema,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "update_unit_op",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _uo_error(unit_op_id, e)
    fields = [
        k
        for k, v in (
            ("name", name),
            ("category", category),
            ("description", description),
            ("param_schema", param_schema),
            ("result_schema", result_schema),
        )
        if v is not None
    ]
    ctx.deps.tool_calls.append(
        {
            "tool": "update_unit_op",
            "subagent": "protocol_builder",
            "unit_op_id": unit_op_id,
            "fields_updated": fields,
        }
    )
    return UnitOpMutationResult(
        ok=True,
        unit_op_id=str(op.id),
        name=op.name,
        summary=f"Updated unit op '{op.name}' ({', '.join(fields)}).",
    )


async def elevate_unit_op_scope(
    ctx: RunContext[ChatDeps],
    unit_op_id: str,
) -> UnitOpMutationResult:
    """Promote a project-scoped unit op to org-wide. Org-admin only."""
    uoid = UUID(unit_op_id)
    try:
        op = await elevate_unit_op_scope_service(
            ctx.deps.db,
            user_id=ctx.deps.user_id,
            org_id=ctx.deps.org_id,
            is_org_admin=ctx.deps.is_org_admin,
            unit_op_id=uoid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append(
            {
                "tool": "elevate_unit_op_scope",
                "subagent": "protocol_builder",
                "error": str(e),
            }
        )
        return _uo_error(unit_op_id, e)
    ctx.deps.tool_calls.append(
        {
            "tool": "elevate_unit_op_scope",
            "subagent": "protocol_builder",
            "unit_op_id": unit_op_id,
        }
    )
    return UnitOpMutationResult(
        ok=True,
        unit_op_id=str(op.id),
        name=op.name,
        summary=f"Elevated unit op '{op.name}' to org-wide scope.",
    )

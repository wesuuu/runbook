"""Service: create a UnitOpDefinition (org- or project-scoped).

Single canonical implementation called by:
  - api/endpoints/unit_ops.py::create_unit_op (HTTP — protocol editor button)
  - subagents/protocol_builder/tools.py::create_unit_op (chat tool)
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.protocols import UnitOpDefinition


async def create_unit_op_definition(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    scope: str,
    name: str,
    category: str,
    description: str,
    param_schema: dict[str, Any],
    project_id: UUID | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpDefinition:
    """Create a unit op definition.

    Raises ValueError on validation errors. The caller is responsible for
    upstream concerns:
      - resolving `is_org_admin` from JWT/membership (HTTP) or from
        ChatDeps.is_org_admin (chat)
      - validating that `project_id`, if given, belongs to `org_id`
        (HTTP endpoint only — chat tool doesn't accept arbitrary project IDs)
    """
    if scope == "org":
        if not is_org_admin:
            raise ValueError(
                "Only organization admins can create org-wide unit "
                "operations. Use scope='project' instead."
            )
        target_org: UUID | None = org_id
        target_proj: UUID | None = None
    elif scope == "project":
        if project_id is None:
            raise ValueError("project_id is required for project-scoped unit ops")
        target_org = org_id
        target_proj = project_id
    else:
        raise ValueError("scope must be 'org' or 'project'")

    existing = await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.name == name,
            (UnitOpDefinition.organization_id == org_id)
            | (UnitOpDefinition.organization_id.is_(None)),
        )
    )
    if existing.scalars().first():
        raise ValueError(f"Unit op '{name}' already exists")

    op = UnitOpDefinition(
        name=name,
        category=category,
        description=description,
        param_schema=param_schema,
        result_schema=result_schema if result_schema is not None else {},
        organization_id=target_org,
        project_id=target_proj,
    )
    db.add(op)
    await db.flush()
    return op


async def _load_op_or_raise(
    db: AsyncSession, unit_op_id: UUID, org_id: UUID
) -> UnitOpDefinition:
    op = (
        await db.execute(
            select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
        )
    ).scalar_one_or_none()
    if op is None:
        raise ValueError(f"Unit op {unit_op_id} not found")
    if op.organization_id is not None and op.organization_id != org_id:
        raise ValueError("Unit op belongs to another organization")
    return op


def _require_not_library(op: UnitOpDefinition) -> None:
    if op.source_library_slug is not None:
        raise ValueError(
            "Cannot modify a library-override unit op — "
            "manage it via the library subscription."
        )


async def update_unit_op_definition(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    unit_op_id: UUID,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    param_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpDefinition:
    """Patch an existing UnitOpDefinition.

    Org-scoped ops require ``is_org_admin``. Project-scoped ops require the
    caller to have validated project EDIT permission upstream. Library-override
    rows are refused — those are managed via the library-subscription flow.
    """
    op = await _load_op_or_raise(db, unit_op_id, org_id)
    _require_not_library(op)
    if op.project_id is None and not is_org_admin:
        raise ValueError(
            "Only organization admins can update org-wide unit operations."
        )
    if name is not None:
        op.name = name
    if category is not None:
        op.category = category
    if description is not None:
        op.description = description
    if param_schema is not None:
        op.param_schema = param_schema
    if result_schema is not None:
        op.result_schema = result_schema
    await db.flush()
    return op


async def elevate_unit_op_scope(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    unit_op_id: UUID,
) -> UnitOpDefinition:
    """Promote a project-scoped unit op to org-scoped.

    Project → org only. Org-admin required. Refuses if the op is already at
    org or global scope, if it is a library override, or if an org-scoped op
    with the same name already exists.
    """
    op = await _load_op_or_raise(db, unit_op_id, org_id)
    _require_not_library(op)
    if op.project_id is None:
        raise ValueError("Unit op is already at org or global scope.")
    if not is_org_admin:
        raise ValueError("Only organization admins can elevate unit ops to org scope.")
    collision = (
        (
            await db.execute(
                select(UnitOpDefinition).where(
                    UnitOpDefinition.organization_id == org_id,
                    UnitOpDefinition.project_id.is_(None),
                    UnitOpDefinition.name == op.name,
                    UnitOpDefinition.id != op.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if collision is not None:
        raise ValueError(f"An org-wide unit op named '{op.name}' already exists.")
    op.project_id = None
    await db.flush()
    return op

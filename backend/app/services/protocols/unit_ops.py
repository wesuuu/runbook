"""Service: create a UnitOpDefinition (org- or project-scoped).

Single canonical implementation called by:
  - api/endpoints/unit_ops.py::create_unit_op (HTTP — protocol editor button)
  - subagents/protocol_builder/tools.py::create_unit_op (chat tool)
"""
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import UnitOpDefinition


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

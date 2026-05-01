"""Service: list and read protocols the user can see.

Single canonical implementation called by:
  - api/endpoints/protocols.py::list_project_protocols, get_protocol
  - subagents/protocol_builder/tools.py::list_protocols, get_protocol
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.iam import (ObjectPermission, ObjectType, PermissionLevel,
                            PrincipalType)
from app.models.science import (Project, Protocol, ProtocolRole,
                                ProtocolVersion)
from app.services.core.permissions import check_permission


@dataclass
class ProtocolListItem:
    id: UUID
    name: str
    description: str | None
    project_id: UUID | None
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool


@dataclass
class ProtocolFull:
    id: UUID
    name: str
    description: str | None
    project_id: UUID | None
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool
    graph: dict[str, Any]
    roles: list[ProtocolRole]


async def list_protocols(
    db,
    *,
    user_id: UUID,
    project_id: UUID | None = None,
) -> list[ProtocolListItem]:
    """Return protocols the user can VIEW. Optionally filter to one project."""
    # Subquery: project_ids the user has any permission on (USER principal).
    # Org-admin / role-based access is honored by check_permission below; this
    # subquery is a fast pre-filter to avoid scanning every protocol.
    perm_proj_q = select(ObjectPermission.object_id).where(
        ObjectPermission.principal_type == PrincipalType.USER,
        ObjectPermission.principal_id == user_id,
        ObjectPermission.object_type == ObjectType.PROJECT.value,
    )
    perm_proj_ids = {row[0] for row in (await db.execute(perm_proj_q)).all()}

    has_draft_subq = (
        select(ProtocolVersion.protocol_id)
        .where(ProtocolVersion.is_draft.is_(True))
        .subquery()
    )

    stmt = (
        select(Protocol, Project.name, has_draft_subq.c.protocol_id)
        .join(Project, Protocol.project_id == Project.id)
        .outerjoin(has_draft_subq, has_draft_subq.c.protocol_id == Protocol.id)
        .where(Protocol.project_id.in_(perm_proj_ids) if perm_proj_ids
               else Protocol.id.is_(None))
        .order_by(Protocol.name)
    )
    if project_id is not None:
        stmt = stmt.where(Protocol.project_id == project_id)

    rows = (await db.execute(stmt)).all()
    return [
        ProtocolListItem(
            id=p.id,
            name=p.name,
            description=p.description,
            project_id=p.project_id,
            project_name=proj_name,
            status=p.status,
            version_number=p.version_number,
            has_draft=draft_id is not None,
        )
        for p, proj_name, draft_id in rows
    ]


async def get_protocol_full(
    db, *, user_id: UUID, protocol_id: UUID
) -> ProtocolFull:
    """Return one protocol's full state (metadata, graph, roles).

    Raises ValueError on missing protocol or missing VIEW permission.
    """
    stmt = (
        select(Protocol, Project.name)
        .outerjoin(Project, Protocol.project_id == Project.id)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    protocol, project_name = row

    if protocol.project_id is not None:
        allowed = await check_permission(
            db, user_id, ObjectType.PROJECT, protocol.project_id,
            PermissionLevel.VIEW,
        )
        if not allowed:
            raise ValueError("You don't have permission to view this protocol")

    draft_q = select(func.count()).where(
        ProtocolVersion.protocol_id == protocol.id,
        ProtocolVersion.is_draft.is_(True),
    )
    has_draft = (await db.execute(draft_q)).scalar_one() > 0

    return ProtocolFull(
        id=protocol.id,
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        project_name=project_name,
        status=protocol.status,
        version_number=protocol.version_number,
        has_draft=has_draft,
        graph=protocol.graph or {},
        roles=list(protocol.roles),
    )

"""Service: list and read protocols the user can see.

Single canonical implementation called by:
  - api/endpoints/protocols.py::list_project_protocols, get_protocol
  - subagents/protocol_builder/tools.py::list_protocols, get_protocol
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Project, Protocol, ProtocolRole, ProtocolVersion
from app.services.core.permissions import check_permission, get_visible_project_ids


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
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    project_id: UUID | None = None,
) -> list[ProtocolListItem]:
    """Return protocols the user can VIEW. Optionally filter to one project.

    Visibility honors org-admin status, direct user permissions, team
    permissions, and projects with `permissions_enabled=false` (open to all
    org members) — see ``get_visible_project_ids``.
    """
    visible_project_ids = await get_visible_project_ids(db, user_id, org_id)
    if not visible_project_ids:
        return []

    has_draft_subq = (
        select(ProtocolVersion.protocol_id)
        .where(ProtocolVersion.is_draft.is_(True))
        .subquery()
    )

    stmt = (
        select(Protocol, Project.name, has_draft_subq.c.protocol_id)
        .join(Project, Protocol.project_id == Project.id)
        .outerjoin(has_draft_subq, has_draft_subq.c.protocol_id == Protocol.id)
        .where(Protocol.project_id.in_(visible_project_ids))
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
    db: AsyncSession, *, user_id: UUID, protocol_id: UUID
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
            db,
            user_id,
            ObjectType.PROJECT,
            protocol.project_id,
            PermissionLevel.VIEW,
        )
        if not allowed:
            raise ValueError("You don't have permission to view this protocol")

    # Pull the latest draft (if any) once, so we can both flag has_draft
    # and surface the draft's graph/name/description on APPROVED protocols
    # — chat tools that just mutated the draft need to read their own
    # work, not the frozen published graph.
    draft_row = (
        (
            await db.execute(
                select(ProtocolVersion)
                .where(
                    ProtocolVersion.protocol_id == protocol.id,
                    ProtocolVersion.is_draft.is_(True),
                )
                .order_by(ProtocolVersion.version_number.desc())
            )
        )
        .scalars()
        .first()
    )
    has_draft = draft_row is not None

    if draft_row is not None and protocol.status == "APPROVED":
        graph = draft_row.graph or {}
        name = draft_row.name or protocol.name
        description = (
            draft_row.description
            if draft_row.description is not None
            else protocol.description
        )
        version_number = draft_row.version_number
    else:
        graph = protocol.graph or {}
        name = protocol.name
        description = protocol.description
        version_number = protocol.version_number

    return ProtocolFull(
        id=protocol.id,
        name=name,
        description=description,
        project_id=protocol.project_id,
        project_name=project_name,
        status=protocol.status,
        version_number=version_number,
        has_draft=has_draft,
        graph=graph,
        roles=list(protocol.roles),
    )

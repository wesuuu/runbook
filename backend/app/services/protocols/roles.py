"""Service: CRUD on ProtocolRole rows.

Mutations require DRAFT status on the parent protocol + project EDIT perm.
Reads require VIEW. Single canonical impl shared by:
  - api/endpoints/protocols.py role endpoints
  - subagents/protocol_builder/tools.py role tools
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Protocol, ProtocolRole
from app.services.core.permissions import check_permission


async def _load_protocol_or_raise(db: AsyncSession, protocol_id: UUID) -> Protocol:
    p = (
        await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    ).scalar_one_or_none()
    if p is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    return p


async def _require_view(db: AsyncSession, user_id: UUID, protocol: Protocol) -> None:
    if protocol.project_id is None:
        return
    allowed = await check_permission(
        db,
        user_id,
        ObjectType.PROJECT,
        protocol.project_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise ValueError("You don't have permission to view this protocol")


async def _require_draft_and_edit(
    db: AsyncSession, user_id: UUID, protocol: Protocol
) -> None:
    if protocol.project_id is None:
        return
    allowed = await check_permission(
        db,
        user_id,
        ObjectType.PROJECT,
        protocol.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise ValueError("You don't have edit permission on this protocol")
    if protocol.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )


async def list_roles(
    db: AsyncSession, *, user_id: UUID, protocol_id: UUID
) -> list[ProtocolRole]:
    proto = await _load_protocol_or_raise(db, protocol_id)
    await _require_view(db, user_id, proto)
    rows = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return list(rows.scalars().all())


async def add_role(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    name: str,
    color: str = "#94a3b8",
    sort_order: int | None = None,
) -> ProtocolRole:
    proto = await _load_protocol_or_raise(db, protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    if sort_order is None:
        max_so = (
            await db.execute(
                select(func.coalesce(func.max(ProtocolRole.sort_order), -1)).where(
                    ProtocolRole.protocol_id == protocol_id
                )
            )
        ).scalar_one()
        sort_order = max_so + 1
    role = ProtocolRole(
        protocol_id=protocol_id,
        name=name,
        color=color,
        sort_order=sort_order,
    )
    db.add(role)
    await db.flush()
    return role


async def update_role(
    db: AsyncSession,
    *,
    user_id: UUID,
    role_id: UUID,
    name: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
) -> ProtocolRole:
    role = (
        await db.execute(select(ProtocolRole).where(ProtocolRole.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    proto = await _load_protocol_or_raise(db, role.protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    if name is not None:
        role.name = name
    if color is not None:
        role.color = color
    if sort_order is not None:
        role.sort_order = sort_order
    await db.flush()
    return role


async def remove_role(db: AsyncSession, *, user_id: UUID, role_id: UUID) -> None:
    role = (
        await db.execute(select(ProtocolRole).where(ProtocolRole.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    proto = await _load_protocol_or_raise(db, role.protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    await db.delete(role)
    await db.flush()

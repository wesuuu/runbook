"""Service: CRUD on ProtocolRole rows.

Mutations require DRAFT status on the parent protocol + project EDIT perm.
Reads require VIEW. Single canonical impl shared by:
  - api/endpoints/protocols.py role endpoints
  - subagents/protocol_builder/tools.py role tools

Role mutations also keep the protocol graph in sync:
  - add_role appends a swimLane node mirroring what the editor inserts
  - update_role patches the lane node's label/color
  - remove_role drops the lane node and clears parentId on nested steps
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.protocols import Protocol, ProtocolRole
from app.services.core.permissions import check_permission


def _lane_id(role_id: UUID) -> str:
    return f"lane-{role_id}"


def _build_lane_node(
    role: ProtocolRole, layout: str, role_index: int
) -> dict[str, Any]:
    """Mirror frontend createSwimLaneNode (protocolNodes.ts)."""
    lane_offset = role_index * 220
    if layout == "vertical":
        position = {"x": lane_offset, "y": 0}
        style = "width: 220px; height: 500px;"
    else:
        position = {"x": 0, "y": lane_offset}
        style = "width: 800px; height: 200px;"
    return {
        "id": _lane_id(role.id),
        "type": "swimLane",
        "zIndex": -1,
        "position": position,
        "data": {
            "label": role.name,
            "color": role.color,
            "roleId": str(role.id),
            "orientation": layout,
        },
        "style": style,
    }


def _graph_layout(graph: dict) -> str:
    layout = graph.get("layout")
    return "vertical" if layout == "vertical" else "horizontal"


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
) -> "WorkingDraft":
    from app.services.protocols.draft import WorkingDraft, resolve_working_draft

    if protocol.project_id is not None:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            protocol.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    return await resolve_working_draft(db, protocol)


async def assert_role_on_protocol(
    db: AsyncSession, *, protocol_id: UUID, role_id: UUID
) -> None:
    """Raise ValueError if ``role_id`` is not a ProtocolRole on ``protocol_id``.

    Use this anywhere ``role_id`` flows in from an external caller (chat tool,
    API endpoint) before writing it to a node's ``parentId``. Without this
    check, an LLM-fabricated or stale UUID becomes an orphaned ``parentId``
    in the graph — the validator catches it after the fact, but only as a
    warning, and that's how the protocol_builder once wrote a non-existent
    "operator role" into a draft and reported success.
    """
    result = await db.execute(
        select(ProtocolRole.id).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise ValueError(
            f"Role {role_id} does not exist on protocol {protocol_id}. "
            "Call list_protocol_roles to see available roles, or "
            "add_protocol_role to create the role first."
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
    wg = await _require_draft_and_edit(db, user_id, proto)
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

    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    layout = _graph_layout(graph)
    role_index = sum(1 for n in nodes if n.get("type") == "swimLane")
    nodes.append(_build_lane_node(role, layout, role_index))
    graph["nodes"] = nodes
    wg.set_graph(graph)
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
    wg = await _require_draft_and_edit(db, user_id, proto)
    if name is not None:
        role.name = name
    if color is not None:
        role.color = color
    if sort_order is not None:
        role.sort_order = sort_order
    await db.flush()

    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    lane_id = _lane_id(role.id)
    changed = False
    for i, node in enumerate(nodes):
        if node.get("id") == lane_id:
            updated = dict(node)
            data = dict(updated.get("data", {}))
            if name is not None:
                data["label"] = role.name
            if color is not None:
                data["color"] = role.color
            updated["data"] = data
            nodes[i] = updated
            changed = True
            break
    if changed:
        graph["nodes"] = nodes
        wg.set_graph(graph)
        await db.flush()
    return role


async def remove_role(db: AsyncSession, *, user_id: UUID, role_id: UUID) -> None:
    role = (
        await db.execute(select(ProtocolRole).where(ProtocolRole.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    proto = await _load_protocol_or_raise(db, role.protocol_id)
    wg = await _require_draft_and_edit(db, user_id, proto)
    lane_id = _lane_id(role.id)
    await db.delete(role)
    await db.flush()

    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    new_nodes: list[dict] = []
    removed = False
    for node in nodes:
        if node.get("id") == lane_id:
            removed = True
            continue
        if node.get("parentId") == lane_id:
            cleaned = dict(node)
            cleaned.pop("parentId", None)
            cleaned.pop("extent", None)
            new_nodes.append(cleaned)
        else:
            new_nodes.append(node)
    if removed or new_nodes != nodes:
        graph["nodes"] = new_nodes
        wg.set_graph(graph)
        await db.flush()

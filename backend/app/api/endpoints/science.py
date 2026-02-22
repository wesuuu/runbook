from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.services.pdf import generate_sop_pdf, generate_batch_record_pdf
from app.models.iam import (
    User,
    ObjectType,
    PermissionLevel,
    ObjectPermission,
    OrganizationMember,
    TeamMember,
)
from app.models.science import (
    UnitOpDefinition,
    Protocol,
    ProtocolVersion,
    Run,
    ProtocolRole,
    Project,
    RunRoleAssignment,
)
from app.schemas.science import (
    UnitOpDefinitionCreate,
    UnitOpDefinitionUpdate,
    UnitOpDefinitionResponse,
    ProtocolCreate,
    ProtocolUpdate,
    ProtocolResponse,
    ProtocolRoleCreate,
    ProtocolRoleUpdate,
    ProtocolRoleResponse,
    ProtocolVersionListItem,
    ProtocolVersionResponse,
    ProtocolApprovalAction,
    RunCreate,
    RunUpdate,
    RunResponse,
    RunRoleAssignmentCreate,
    RunRoleAssignmentResponse,
    RunRoleAssignmentListResponse,
)
from app.schemas.iam import UserSearchResponse
from app.services.audit import log_audit
from app.services.permissions import check_permission

router = APIRouter()


# --- UnitOps (auth only, no per-object perms) ---

@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UnitOpDefinition))
    return result.scalars().all()


@router.post(
    "/unit-ops",
    response_model=UnitOpDefinitionResponse,
    status_code=201,
)
async def create_unit_op(
    unit_op: UnitOpDefinitionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_op = UnitOpDefinition(
        name=unit_op.name,
        category=unit_op.category,
        description=unit_op.description,
        param_schema=unit_op.param_schema,
    )
    db.add(new_op)
    await db.commit()
    await db.refresh(new_op)
    return new_op


@router.put(
    "/unit-ops/{unit_op_id}",
    response_model=UnitOpDefinitionResponse,
)
async def update_unit_op(
    unit_op_id: UUID,
    update_data: UnitOpDefinitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a global unit op definition.

    Args:
        unit_op_id: The UUID of the unit op to update.
        update_data: Partial update fields.
        user: Authenticated user.
        db: Async DB session.

    Returns:
        Updated UnitOpDefinitionResponse.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = result.scalar_one_or_none()
    if not unit_op:
        raise HTTPException(status_code=404, detail="Unit op not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return unit_op


# --- Protocols ---

@router.post(
    "/protocols", response_model=ProtocolResponse, status_code=201,
)
async def create_protocol(
    protocol: ProtocolCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check user has EDIT on the parent project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == protocol.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    new_protocol = Protocol(
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        graph=protocol.graph,
    )
    db.add(new_protocol)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Protocol",
        new_protocol.id,
        {"name": protocol.name, "version_number": new_protocol.version_number},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == new_protocol.id)
    )
    return result.scalar_one()


@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.get(
    "/projects/{project_id}/protocols",
    response_model=List[ProtocolResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_protocols(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.project_id == project_id)
    )
    return result.scalars().all()


@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(
    protocol_id: UUID,
    update_data: ProtocolUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    changes = update_data.model_dump(exclude_unset=True)

    # Block edits while pending approval
    if protocol.status == "PENDING_APPROVAL" and "graph" in changes:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit protocol while pending approval",
        )

    # If graph is being updated, create a version snapshot
    if "graph" in changes:
        protocol.version_number += 1
        version = ProtocolVersion(
            protocol_id=protocol.id,
            version_number=protocol.version_number,
            graph=changes["graph"],
            name=changes.get("name", protocol.name),
            description=changes.get("description", protocol.description),
            created_by_id=user.id,
        )
        db.add(version)

        # Revert approved protocol to draft on edit
        if protocol.status == "APPROVED":
            protocol.status = "DRAFT"

    for key, value in changes.items():
        setattr(protocol, key, value)

    audit_changes = dict(changes)
    if "graph" in changes:
        audit_changes["version_number"] = protocol.version_number
    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id, audit_changes,
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Protocol Roles (inherit project perms) ---

@router.get(
    "/protocols/{protocol_id}/roles",
    response_model=List[ProtocolRoleResponse],
)
async def list_protocol_roles(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return result.scalars().all()


@router.post(
    "/protocols/{protocol_id}/roles",
    response_model=ProtocolRoleResponse,
    status_code=201,
)
async def create_protocol_role(
    protocol_id: UUID,
    role: ProtocolRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Protocol not found")

    new_role = ProtocolRole(
        protocol_id=protocol_id,
        name=role.name,
        color=role.color,
        sort_order=role.sort_order,
    )
    db.add(new_role)
    await db.commit()
    await db.refresh(new_role)
    return new_role


@router.put(
    "/protocols/{protocol_id}/roles/{role_id}",
    response_model=ProtocolRoleResponse,
)
async def update_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    update_data: ProtocolRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(role, key, value)

    await db.commit()
    await db.refresh(role)
    return role


def _topo_sort_nodes(
    component_ids: set[str],
    edges: list[dict],
    node_map: dict[str, dict],
) -> list[dict]:
    """Topologically sort nodes within a connected component.

    Falls back to x-position ordering for nodes at the same depth
    or when cycles exist.
    """
    directed: dict[str, list[str]] = {nid: [] for nid in component_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in component_ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in component_ids and tgt in component_ids:
            directed[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    # Kahn's algorithm — use x-position to break ties
    def _x(nid: str) -> float:
        return node_map[nid].get("position", {}).get("x", 0)

    queue = sorted(
        [nid for nid in component_ids if in_degree[nid] == 0],
        key=_x,
    )
    result: list[str] = []
    while queue:
        curr = queue.pop(0)
        result.append(curr)
        for neighbor in directed[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=_x)

    # Remaining nodes (cycles) — append sorted by x-position
    visited = set(result)
    for nid in sorted(component_ids - visited, key=_x):
        result.append(nid)

    return [node_map[nid] for nid in result]


def _find_connected_components(
    unit_ops: list[dict],
    edges: list[dict],
) -> list[list[dict]]:
    """Group unit-op nodes into connected components based on edges.

    Each component is topologically sorted by edge direction,
    with x-position as tie-breaker.
    """
    node_map = {n["id"]: n for n in unit_ops}
    unit_op_ids = set(node_map.keys())

    # Build undirected adjacency for component discovery
    adj: dict[str, set[str]] = {nid: set() for nid in unit_op_ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in unit_op_ids and tgt in unit_op_ids:
            adj[src].add(tgt)
            adj[tgt].add(src)

    # BFS to find components
    visited: set[str] = set()
    components: list[list[dict]] = []
    for nid in unit_op_ids:
        if nid in visited:
            continue
        comp_ids: set[str] = set()
        queue = [nid]
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            comp_ids.add(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    queue.append(neighbor)
        sorted_nodes = _topo_sort_nodes(comp_ids, edges, node_map)
        components.append(sorted_nodes)

    # Sort components by the x-position of their first node
    components.sort(
        key=lambda c: c[0].get("position", {}).get("x", 0) if c else 0,
    )
    return components


def _parse_graph_roles_and_steps(graph: dict) -> tuple[list[dict], list[dict]]:
    """Extract roles and ordered steps from a protocol/run graph.

    Returns:
        (roles_with_steps, flat_steps) where roles_with_steps is a list
        of dicts with role_name and steps, and flat_steps is all steps
        with role_name attached (for batch record).
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    unit_ops = sorted(
        [n for n in nodes if n.get("type") == "unitOp"],
        key=lambda n: n.get("position", {}).get("x", 0),
    )
    swim_lanes = {
        n["id"]: n for n in nodes if n.get("type") == "swimLane"
    }

    # Check if any unitOps are parented to swimlanes
    any_parented = any(
        n.get("parentId") and n["parentId"] in swim_lanes
        for n in unit_ops
    )

    def _step_dict(node: dict, role_name: str) -> dict:
        data = node.get("data", {})
        return {
            "id": node["id"],
            "name": data.get("label", "Unnamed"),
            "description": data.get("description", ""),
            "params": data.get("params"),
            "param_schema": data.get("paramSchema"),
            "duration_min": data.get("duration_min"),
            "role_name": role_name,
        }

    roles_with_steps: list[dict] = []
    flat_steps: list[dict] = []

    if any_parented and swim_lanes:
        # Group by swimlane
        for lane_id, lane in swim_lanes.items():
            lane_name = lane.get("data", {}).get("label", "Unknown Role")
            lane_steps = [
                _step_dict(n, lane_name)
                for n in unit_ops
                if n.get("parentId") == lane_id
            ]
            if lane_steps:
                roles_with_steps.append({
                    "role_name": lane_name,
                    "steps": lane_steps,
                })
                flat_steps.extend(lane_steps)

        # Include orphaned steps (not parented to any lane)
        orphans = [
            n for n in unit_ops
            if not n.get("parentId") or n["parentId"] not in swim_lanes
        ]
        if orphans:
            orphan_steps = [_step_dict(n, "Unassigned") for n in orphans]
            roles_with_steps.append({
                "role_name": "Unassigned",
                "steps": orphan_steps,
            })
            flat_steps.extend(orphan_steps)
    else:
        # No swimlane parenting — group by connected components
        components = _find_connected_components(unit_ops, edges)
        multi_process = len(components) > 1

        for comp_nodes in components:
            first_label = comp_nodes[0].get("data", {}).get(
                "label", "Process"
            ) if comp_nodes else "Process"
            process_name = first_label if multi_process else ""
            comp_steps = [_step_dict(n, process_name) for n in comp_nodes]
            roles_with_steps.append({
                "role_name": process_name,
                "steps": comp_steps,
            })
            flat_steps.extend(comp_steps)

    return roles_with_steps, flat_steps


# --- Protocol Version History ---

@router.get(
    "/protocols/{protocol_id}/versions",
    response_model=List[ProtocolVersionListItem],
)
async def list_protocol_versions(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolVersion)
        .options(selectinload(ProtocolVersion.created_by))
        .where(ProtocolVersion.protocol_id == protocol_id)
        .order_by(ProtocolVersion.version_number.desc())
    )
    versions = result.scalars().all()

    return [
        ProtocolVersionListItem(
            id=v.id,
            version_number=v.version_number,
            name=v.name,
            change_summary=v.change_summary,
            created_by_name=(
                v.created_by.full_name or v.created_by.email
                if v.created_by else None
            ),
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.get(
    "/protocols/{protocol_id}/versions/{version_number}",
    response_model=ProtocolVersionResponse,
)
async def get_protocol_version(
    protocol_id: UUID,
    version_number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolVersion)
        .options(selectinload(ProtocolVersion.created_by))
        .where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return ProtocolVersionResponse(
        id=version.id,
        protocol_id=version.protocol_id,
        version_number=version.version_number,
        graph=version.graph,
        name=version.name,
        description=version.description,
        change_summary=version.change_summary,
        created_by_id=version.created_by_id,
        created_by_name=(
            version.created_by.full_name or version.created_by.email
            if version.created_by else None
        ),
        created_at=version.created_at,
    )


@router.post(
    "/protocols/{protocol_id}/revert/{version_number}",
    response_model=ProtocolResponse,
)
async def revert_protocol_version(
    protocol_id: UUID,
    version_number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol.status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail="Cannot revert protocol while pending approval",
        )

    result = await db.execute(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.version_number == version_number,
        )
    )
    old_version = result.scalar_one_or_none()
    if not old_version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Create new version with the reverted graph
    protocol.version_number += 1
    protocol.graph = old_version.graph

    new_version = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=protocol.version_number,
        graph=old_version.graph,
        name=protocol.name,
        description=protocol.description,
        created_by_id=user.id,
        change_summary=f"Reverted to v{version_number}",
    )
    db.add(new_version)

    if protocol.status == "APPROVED":
        protocol.status = "DRAFT"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id,
        {
            "reverted_to_version": version_number,
            "version_number": protocol.version_number,
        },
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Protocol Approval ---

@router.post(
    "/protocols/{protocol_id}/submit-for-approval",
    response_model=ProtocolResponse,
)
async def submit_protocol_for_approval(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol.status != "DRAFT":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit: protocol is {protocol.status}",
        )

    protocol.status = "PENDING_APPROVAL"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id,
        {"status": "PENDING_APPROVAL"},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


@router.post(
    "/protocols/{protocol_id}/approve",
    response_model=ProtocolResponse,
)
async def approve_protocol(
    protocol_id: UUID,
    action: ProtocolApprovalAction,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Require APPROVE permission on the parent project
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol_obj.project_id, PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required on project",
        )

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: protocol is {protocol_obj.status}",
        )

    protocol_obj.status = "APPROVED"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol_obj.id,
        {"status": "APPROVED", "comment": action.comment},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_obj.id)
    )
    return result.scalar_one()


@router.post(
    "/protocols/{protocol_id}/reject",
    response_model=ProtocolResponse,
)
async def reject_protocol(
    protocol_id: UUID,
    action: ProtocolApprovalAction,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Require APPROVE permission on the parent project
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol_obj.project_id, PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required on project",
        )

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: protocol is {protocol_obj.status}",
        )

    protocol_obj.status = "DRAFT"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol_obj.id,
        {"status": "DRAFT", "action": "rejected", "comment": action.comment},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_obj.id)
    )
    return result.scalar_one()


# --- Protocol PDF ---

@router.get("/protocols/{protocol_id}/pdf/sop")
async def get_protocol_sop_pdf(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF preview from a protocol's graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    graph = protocol.graph or {}
    roles_with_steps, _ = _parse_graph_roles_and_steps(graph)

    pdf_bytes = generate_sop_pdf(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name=None,
        roles_with_steps=roles_with_steps,
    )

    filename = f"SOP_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Run PDFs ---

@router.get("/runs/{run_id}/pdf/sop")
async def get_run_sop_pdf(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get protocol name and description
    protocol_name = "Unknown Protocol"
    protocol_description = ""
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name
            protocol_description = proto.description or ""

    graph = run_obj.graph or {}
    roles_with_steps, _ = _parse_graph_roles_and_steps(graph)

    pdf_bytes = generate_sop_pdf(
        protocol_name=protocol_name,
        protocol_description=protocol_description,
        run_name=run_obj.name,
        roles_with_steps=roles_with_steps,
    )

    filename = f"SOP_{run_obj.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/pdf/batch-record")
async def get_run_batch_record_pdf(
    run_id: UUID,
    filled: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a batch record PDF from a run's snapshot graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get protocol name
    protocol_name = "Unknown Protocol"
    if run_obj.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_obj.protocol_id)
        )
        proto = result.scalar_one_or_none()
        if proto:
            protocol_name = proto.name

    graph = run_obj.graph or {}
    roles_with_steps, flat_steps = _parse_graph_roles_and_steps(graph)

    # Build roles list for sign-off
    roles = [
        {"id": r["role_name"], "name": r["role_name"]}
        for r in roles_with_steps
        if r["role_name"]
    ]
    if not roles:
        roles = [{"id": "all", "name": "All Steps"}]

    pdf_bytes = generate_batch_record_pdf(
        protocol_name=protocol_name,
        run_name=run_obj.name,
        roles=roles,
        steps=flat_steps,
        filled=filled,
        execution_data=run_obj.execution_data if filled else None,
    )

    suffix = "COMPLETED" if filled else "BLANK"
    filename = f"BatchRecord_{run_obj.name}_{suffix}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/protocols/{protocol_id}/roles/{role_id}")
async def delete_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    await db.delete(role)
    await db.commit()
    return {"ok": True}


# --- Runs ---

@router.post(
    "/runs", response_model=RunResponse, status_code=201,
)
async def create_run(
    run_in: RunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        run_in.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == run_in.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph = {}
    if run_in.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_in.protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if protocol:
            initial_graph = protocol.graph.copy() if protocol.graph else {}

    run_obj = Run(
        name=run_in.name,
        project_id=run_in.project_id,
        protocol_id=run_in.protocol_id,
        graph=initial_graph,
        execution_data={},
    )
    db.add(run_obj)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Run",
        run_obj.id, {"name": run_in.name},
    )

    await db.commit()
    await db.refresh(run_obj)
    return run_obj


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_obj


@router.get(
    "/projects/{project_id}/runs",
    response_model=List[RunResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_runs(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.project_id == project_id)
    )
    return result.scalars().all()


@router.put(
    "/runs/{run_id}", response_model=RunResponse,
)
async def update_run(
    run_id: UUID,
    update_data: RunUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Validate status transition to ACTIVE
    new_status = update_data.status.value if update_data.status else None
    current_status = run_obj.status if isinstance(run_obj.status, str) else run_obj.status.value
    if (new_status and
        new_status == "ACTIVE" and
        current_status != "ACTIVE"):
        # Check that all swimlane roles in the graph have assignments
        graph = run_obj.graph or {}
        nodes = graph.get("nodes", [])
        swimlane_nodes = [n for n in nodes if n.get("type") == "swimLane"]

        if swimlane_nodes:
            result = await db.execute(
                select(RunRoleAssignment)
                .where(RunRoleAssignment.run_id == run_id)
            )
            assignments = result.scalars().all()
            assigned_lanes = {a.lane_node_id for a in assignments}
            required_lanes = {n["id"] for n in swimlane_nodes}

            if assigned_lanes != required_lanes:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot start run: not all roles have assigned users",
                )

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(run_obj, key, value)

    await log_audit(
        db, user.id, "UPDATE", "Run", run_obj.id, changes,
    )

    await db.commit()
    await db.refresh(run_obj)
    return run_obj


# --- Project Members ---

@router.get(
    "/projects/{project_id}/members",
    response_model=List[UserSearchResponse],
)
async def get_project_members(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all users who have access to a project.

    This includes:
    - Users with direct ObjectPermission rows on the project
    - Users who belong to teams with ObjectPermission on the project
    - Organization admins
    """
    # Check VIEW permission on project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Get the project to find its org
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_ids = set()

    # 1. Direct USER permissions on project
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "USER",
        ))
    )
    for perm in result.scalars().all():
        user_ids.add(perm.principal_id)

    # 2. TEAM permissions on project → expand to team members
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "TEAM",
        ))
    )
    team_perms = result.scalars().all()
    if team_perms:
        team_ids = [p.principal_id for p in team_perms]
        result = await db.execute(
            select(TeamMember)
            .where(TeamMember.team_id.in_(team_ids))
        )
        for tm in result.scalars().all():
            user_ids.add(tm.user_id)

    # 3. Organization admins
    result = await db.execute(
        select(OrganizationMember)
        .where(and_(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.is_admin is True,
        ))
    )
    for om in result.scalars().all():
        user_ids.add(om.user_id)

    # Fetch all users
    if not user_ids:
        return []

    result = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users = result.scalars().all()
    return users


# --- Run Role Assignments ---

@router.get(
    "/runs/{run_id}/role-assignments",
    response_model=RunRoleAssignmentListResponse,
)
async def get_run_role_assignments(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all role assignments for a run."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment)
        .where(RunRoleAssignment.run_id == run_id)
    )
    assignments = result.scalars().all()
    return RunRoleAssignmentListResponse(items=assignments)


@router.post(
    "/runs/{run_id}/role-assignments",
    response_model=RunRoleAssignmentResponse,
    status_code=201,
)
async def create_run_role_assignment(
    run_id: UUID,
    assignment: RunRoleAssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a user to a role in a run."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Run).where(Run.id == run_id)
    )
    run_obj = result.scalar_one_or_none()
    if not run_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    # Verify user exists
    result = await db.execute(
        select(User).where(User.id == assignment.user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    # Check if assignment already exists for this lane
    result = await db.execute(
        select(RunRoleAssignment)
        .where(and_(
            RunRoleAssignment.run_id == run_id,
            RunRoleAssignment.lane_node_id == assignment.lane_node_id,
        ))
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Update existing assignment
        existing.user_id = assignment.user_id
        existing.role_name = assignment.role_name
        await db.commit()
        await db.refresh(existing)
        return existing

    # Create new assignment
    new_assignment = RunRoleAssignment(
        run_id=run_id,
        lane_node_id=assignment.lane_node_id,
        role_name=assignment.role_name,
        user_id=assignment.user_id,
    )
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)
    return new_assignment


@router.delete("/runs/{run_id}/role-assignments/{assignment_id}")
async def delete_run_role_assignment(
    run_id: UUID,
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user's role assignment."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN,
        run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment)
        .where(and_(
            RunRoleAssignment.id == assignment_id,
            RunRoleAssignment.run_id == run_id,
        ))
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await db.delete(assignment)
    await db.commit()
    return {"ok": True}

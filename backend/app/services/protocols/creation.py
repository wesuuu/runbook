"""Service: create a Protocol in a project from a structured spec.

Owns project lookup, EDIT permission check, graph construction, persistence.
Used by both the chat agent's protocol_builder subagent (via a thin tool
wrapper) and any future direct REST endpoint or batch job.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.projects import Project
from app.models.protocols import Protocol, UnitOpDefinition
from app.services.core.permissions import check_permission
from app.services.protocols.lane_layout import grow_lane_to_fit, lane_relative_position
from app.services.slugs import assign_slug


class ProtocolStep(BaseModel):
    name: str
    unit_op_name: str
    category: str = "General"
    description: str = ""
    duration_min: int = 30
    params: dict[str, Any] = Field(default_factory=dict)


class ProtocolSpec(BaseModel):
    name: str
    description: str = ""
    steps: list[ProtocolStep]


async def create_protocol_from_spec(
    db: AsyncSession,
    user_id: UUID,
    project_name: str,
    spec: ProtocolSpec,
) -> Protocol:
    """Create a DRAFT Protocol in the named project from a structured spec.

    Raises ValueError if:
      - spec has no steps
      - project not found
      - user lacks EDIT permission
    """
    if not spec.steps:
        raise ValueError("spec must include at least one step")

    result = await db.execute(
        select(Project)
        .where(Project.name.ilike(f"%{project_name}%"))
        .order_by(Project.created_at.desc())
        .limit(1)
    )
    project = result.scalars().first()
    if project is None:
        raise ValueError(f"Project '{project_name}' not found")

    allowed = await check_permission(
        db,
        user_id,
        ObjectType.PROJECT,
        project.id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise ValueError("You don't have edit permission on this project")

    result = await db.execute(select(UnitOpDefinition))
    unit_ops = list(result.scalars().all())

    # Reuse the existing graph-builder helpers (they will move to
    # workflows/protocol_generator.py in Task 21 — this import path
    # updates then).
    from app.services.ai.workflows.protocol_generator import (
        GeneratedProtocol,
        GeneratedStep,
        build_graph,
    )

    generated = GeneratedProtocol(
        name=spec.name,
        description=spec.description,
        steps=[
            GeneratedStep(
                name=s.name,
                unit_op_name=s.unit_op_name,
                category=s.category,
                description=s.description,
                duration_min=s.duration_min,
                params=s.params,
            )
            for s in spec.steps
        ],
    )
    # build_graph third param is session_id (UUID stored in metadata).
    # Pass zero-UUID since this creation path has no associated chat session.
    graph = build_graph(generated, unit_ops, UUID(int=0), user_id)

    protocol = Protocol(
        name=spec.name,
        description=spec.description,
        project_id=project.id,
        status="DRAFT",
        graph=graph,
    )
    # F-0091: resolve owning org and assign a slug.
    protocol.owner_org_id = project.organization_id
    protocol.slug = await assign_slug(
        db,
        Protocol,
        Protocol.owner_org_id,
        protocol.owner_org_id,
        protocol.name,
    )
    db.add(protocol)
    await db.flush()
    return protocol


async def update_protocol_step(
    db: AsyncSession,
    user_id: UUID,
    protocol_id: UUID,
    step_index: int,
    *,
    description: str | None = None,
    category: str | None = None,
    param_schema: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    role_id: UUID | None = None,
) -> Protocol:
    """Patch a single unit-op step inside an existing DRAFT Protocol's graph.

    Only the kwargs supplied are written. ``role_id`` sets the node's
    ``parentId`` to ``lane-<role_id>`` (frontend lane convention).
    Refuses on APPROVED/PENDING_APPROVAL — published protocols require a
    new draft (out of scope for this service).
    """
    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if protocol is None:
        raise ValueError(f"Protocol {protocol_id} not found")

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

    from app.services.protocols.draft import resolve_working_draft

    wg = await resolve_working_draft(db, protocol)
    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    unit_op_indices = [i for i, n in enumerate(nodes) if n.get("type") == "unitOp"]
    if step_index < 0 or step_index >= len(unit_op_indices):
        raise ValueError(
            f"step_index {step_index} out of range "
            f"(protocol has {len(unit_op_indices)} unit op steps)"
        )

    node_idx = unit_op_indices[step_index]
    node = dict(nodes[node_idx])
    data = dict(node.get("data") or {})

    if description is not None:
        data["description"] = description
    if category is not None:
        data["category"] = category
    if param_schema is not None:
        data["paramSchema"] = param_schema
    if params is not None:
        data["params"] = params

    node["data"] = data
    new_lane_id: str | None = None
    if role_id is not None:
        from app.services.protocols.roles import assert_role_on_protocol

        await assert_role_on_protocol(db, protocol_id=protocol_id, role_id=role_id)
        new_lane_id = f"lane-{role_id}"
        old_parent_id = node.get("parentId")
        if old_parent_id != new_lane_id:
            layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
            node["parentId"] = new_lane_id
            # When parentId is set the position field becomes relative to
            # the parent. The previous absolute coordinates (or relative
            # coords from a different lane) would land the step outside
            # the lane or stacked on top of an existing sibling — pick a
            # fresh slot inside the new lane.
            node["position"] = lane_relative_position(
                nodes, new_lane_id, graph_layout=layout, exclude_node_id=node["id"]
            )

    nodes[node_idx] = node

    if new_lane_id is not None:
        layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
        nodes = grow_lane_to_fit(nodes, new_lane_id, graph_layout=layout)

    graph["nodes"] = nodes
    wg.set_graph(graph)
    await db.flush()
    return protocol


async def update_protocol_metadata(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    name: str | None = None,
    description: str | None = None,
) -> Protocol:
    """Patch an existing DRAFT Protocol's name and/or description.

    Refuses on APPROVED/PENDING_APPROVAL — those require a draft via the
    existing endpoint flow.
    """
    proto = (
        await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    ).scalar_one_or_none()
    if proto is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    if proto.project_id is not None:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            proto.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    from app.services.protocols.draft import resolve_working_draft

    wg = await resolve_working_draft(db, proto)
    if wg.is_version_backed:
        # Metadata edits land on the draft version row; publish-draft
        # promotes the graph but leaves protocol name/description alone,
        # so writing to the version mirrors the editor flow.
        if name is not None:
            if name != wg.version.name:
                # F-0091: re-slug on rename so the URL stays in step with
                # the version name, the same as the non-version-backed
                # branch below.
                proto.slug = await assign_slug(
                    db,
                    Protocol,
                    Protocol.owner_org_id,
                    proto.owner_org_id,
                    name,
                    exclude_id=proto.id,
                )
            wg.version.name = name
        if description is not None:
            wg.version.description = description
    else:
        if name is not None:
            if name != proto.name:
                # F-0091: re-slug when the protocol is renamed.
                new_slug = await assign_slug(
                    db,
                    Protocol,
                    Protocol.owner_org_id,
                    proto.owner_org_id,
                    name,
                    exclude_id=proto.id,
                )
                proto.slug = new_slug
            proto.name = name
        if description is not None:
            proto.description = description
    await db.flush()
    return proto

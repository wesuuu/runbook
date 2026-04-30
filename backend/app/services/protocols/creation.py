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
from app.models.science import Project, Protocol, UnitOpDefinition
from app.services.core.permissions import check_permission


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
        GeneratedProtocol, GeneratedStep, build_graph)

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
) -> Protocol:
    """Patch a single unit-op step inside an existing Protocol's graph.

    Used by the chat agent's auto-fix loop after `validate_protocol` flags
    issues with a specific step. ``step_index`` is the 0-based index of
    the unit-op node among unit-op nodes only (Process Start is excluded).

    Only the kwargs supplied are written; ``None`` leaves the field alone.
    Raises ValueError on missing protocol, missing edit permission, or
    invalid ``step_index``.
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

    graph = dict(protocol.graph or {})
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
    nodes[node_idx] = node
    graph["nodes"] = nodes
    protocol.graph = graph
    await db.flush()
    return protocol

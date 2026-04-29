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

"""Onboarding tour artifact helpers.

Find-or-create sample projects, protocols, and runs used during the guided
tour. Sample protocol/run are flagged with is_tour_sample=True; sample
project is a normal project that the user can rename or delete freely.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run, RunStatus
from app.services.slugs import assign_slug

SAMPLE_PROJECT_NAME = "My First Project"
SAMPLE_PROTOCOL_NAME = "Sample Protocol"
SAMPLE_RUN_NAME = "Sample Run"


def get_sample_protocol_graph() -> dict[str, Any]:
    """Return the pre-populated graph for the sample protocol.

    Vertical layout with a ProcessStart node at the root. Edges connect
    top-to-bottom (handleOrientation="vertical"), matching a typical
    batch-record flow from process kickoff through downstream steps.
    """
    return {
        "nodes": [
            {
                "id": "sample-start",
                "type": "processStart",
                "position": {"x": 400, "y": 40},
                "width": 220,
                "data": {
                    "label": "Start of Protocol",
                    "description": "Marks the beginning of the process. Every protocol has one.",
                },
            },
            {
                "id": "sample-buffer",
                "type": "unitOp",
                "position": {"x": 400, "y": 200},
                "data": {
                    "label": "Buffer Prep",
                    "category": "Media Prep",
                    "duration_min": 30,
                    "description": "Prepare {{volume_L}}L of {{buffer_name}} buffer at pH {{ph}}.",
                    "params": {"buffer_name": "PBS", "volume_L": 10, "ph": 7.4},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "buffer_name": {
                                "type": "string",
                                "title": "Buffer Name",
                                "default": "PBS",
                            },
                            "volume_L": {
                                "type": "number",
                                "title": "Volume (L)",
                                "default": 10,
                            },
                            "ph": {
                                "type": "number",
                                "title": "pH",
                                "default": 7.4,
                            },
                        },
                    },
                },
            },
            {
                "id": "sample-media",
                "type": "unitOp",
                "position": {"x": 400, "y": 400},
                "data": {
                    "label": "Media Prep",
                    "category": "Media Prep",
                    "duration_min": 45,
                    "params": {"media_name": "DMEM", "volume_L": 5},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "media_name": {"type": "string", "default": "DMEM"},
                            "volume_L": {"type": "number", "default": 5},
                        },
                    },
                },
            },
            {
                "id": "sample-seed",
                "type": "unitOp",
                "position": {"x": 400, "y": 600},
                "data": {
                    "label": "Seeding",
                    "category": "Cell Culture",
                    "duration_min": 60,
                    "params": {"cell_density": 1e6},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "cell_density": {"type": "number", "default": 1e6},
                        },
                    },
                },
            },
        ],
        "edges": [
            {"id": "e0", "source": "sample-start", "target": "sample-buffer"},
            {"id": "e1", "source": "sample-buffer", "target": "sample-media"},
            {"id": "e2", "source": "sample-media", "target": "sample-seed"},
        ],
        "layout": "vertical",
        "handleOrientation": "vertical",
        "timeEnabled": False,
        "startTime": "08:00",
        "pixelsPerHour": 200,
    }


async def find_or_create_sample_project(
    db: AsyncSession, user: User, org: Organization
) -> Project:
    """Return any existing project for the org; create 'My First Project' if none."""
    stmt = select(Project).where(Project.organization_id == org.id).limit(1)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if project is not None:
        return project

    project = Project(
        name=SAMPLE_PROJECT_NAME,
        description="Seeded by the onboarding tour.",
        organization_id=org.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def find_or_create_sample_protocol(
    db: AsyncSession, user: User, org: Organization
) -> Protocol:
    """Return the user's org's sample protocol; create with a pre-populated graph if missing.

    Sample protocols are nested under a project (so project_id is set); we match
    by is_tour_sample=True joined to a project in the given org.
    """
    result = await db.execute(
        select(Protocol)
        .join(Project, Project.id == Protocol.project_id)
        .where(
            Protocol.is_tour_sample.is_(True),
            Project.organization_id == org.id,
        )
        .limit(1)
    )
    protocol = result.scalar_one_or_none()
    if protocol is not None:
        return protocol

    project = await find_or_create_sample_project(db, user, org)
    protocol = Protocol(
        name=SAMPLE_PROTOCOL_NAME,
        description="A pre-built sample to illustrate the protocol editor.",
        project_id=project.id,
        status="DRAFT",
        graph=get_sample_protocol_graph(),
        is_tour_sample=True,
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
    await db.commit()
    await db.refresh(protocol)
    return protocol


async def find_or_create_sample_run(
    db: AsyncSession, user: User, protocol: Protocol
) -> Run:
    """Delete any prior sample run for this user, then create a fresh one."""
    await delete_sample_run(db, user)

    run = Run(
        name=SAMPLE_RUN_NAME,
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        status=RunStatus.PLANNED,
        graph=protocol.graph,
        started_by_id=user.id,
        is_tour_sample=True,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def delete_sample_run(db: AsyncSession, user: User) -> None:
    """Delete this user's sample run, if any. Idempotent."""
    stmt = select(Run).where(
        Run.is_tour_sample.is_(True),
        Run.started_by_id == user.id,
    )
    result = await db.execute(stmt)
    for run in result.scalars().all():
        await db.delete(run)
    await db.commit()

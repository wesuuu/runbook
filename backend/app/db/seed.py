"""Centralized seed data for the Runbook application.

Run via: python -m app.db.seed (from backend directory)

Seeds a complete demo organization with users, teams, projects,
permissions, and unit operations. All functions are idempotent
(check-before-insert).
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.iam import (
    Organization,
    OrganizationMember,
    Team,
    TeamMember,
    User,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
    Role,
)
from app.models.science import Project, UnitOpDefinition


# --- Fixed UUIDs for reproducibility ---
ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")

USER_ADMIN = uuid.UUID("20000000-0000-0000-0000-000000000001")
USER_UPSTREAM_LEAD = uuid.UUID("20000000-0000-0000-0000-000000000002")
USER_DOWNSTREAM_LEAD = uuid.UUID("20000000-0000-0000-0000-000000000003")
USER_SCIENTIST1 = uuid.UUID("20000000-0000-0000-0000-000000000004")
USER_SCIENTIST2 = uuid.UUID("20000000-0000-0000-0000-000000000005")
USER_VIEWER = uuid.UUID("20000000-0000-0000-0000-000000000006")

TEAM_UPSTREAM = uuid.UUID("30000000-0000-0000-0000-000000000001")
TEAM_DOWNSTREAM = uuid.UUID("30000000-0000-0000-0000-000000000002")
TEAM_QA = uuid.UUID("30000000-0000-0000-0000-000000000003")

PROJECT_MAB = uuid.UUID("40000000-0000-0000-0000-000000000001")
PROJECT_VACCINE = uuid.UUID("40000000-0000-0000-0000-000000000002")

DEFAULT_PASSWORD = hash_password("password123")


async def _upsert(db: AsyncSession, model, pk_id: uuid.UUID, **kwargs):
    """Insert if not exists (by PK). Returns the object."""
    result = await db.execute(
        select(model).where(model.id == pk_id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    obj = model(id=pk_id, **kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def seed_users(db: AsyncSession):
    users = [
        (USER_ADMIN, "admin@bioprocess.com", "Admin User"),
        (USER_UPSTREAM_LEAD, "upstream.lead@bioprocess.com", "Upstream Lead"),
        (USER_DOWNSTREAM_LEAD, "downstream.lead@bioprocess.com", "Downstream Lead"),
        (USER_SCIENTIST1, "scientist1@bioprocess.com", "Scientist One"),
        (USER_SCIENTIST2, "scientist2@bioprocess.com", "Scientist Two"),
        (USER_VIEWER, "viewer@bioprocess.com", "Viewer User"),
    ]
    for uid, email, name in users:
        await _upsert(
            db, User, uid,
            email=email,
            hashed_password=DEFAULT_PASSWORD,
            full_name=name,
        )


async def seed_org(db: AsyncSession):
    await _upsert(db, Organization, ORG_ID, name="BioProcess Inc")

    # Org memberships
    members = [
        (USER_ADMIN, True),
        (USER_UPSTREAM_LEAD, False),
        (USER_DOWNSTREAM_LEAD, False),
        (USER_SCIENTIST1, False),
        (USER_SCIENTIST2, False),
        (USER_VIEWER, False),
    ]
    for uid, is_admin in members:
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == uid,
                OrganizationMember.organization_id == ORG_ID,
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(OrganizationMember(
                user_id=uid,
                organization_id=ORG_ID,
                is_admin=is_admin,
            ))
    await db.flush()


async def seed_teams(db: AsyncSession):
    teams = [
        (TEAM_UPSTREAM, "Upstream Team"),
        (TEAM_DOWNSTREAM, "Downstream Team"),
        (TEAM_QA, "QA Team"),
    ]
    for tid, name in teams:
        await _upsert(db, Team, tid, name=name, organization_id=ORG_ID)

    # Team memberships: (team_id, user_id, role)
    memberships = [
        (TEAM_UPSTREAM, USER_UPSTREAM_LEAD, Role.OWNER),
        (TEAM_UPSTREAM, USER_SCIENTIST1, Role.MEMBER),
        (TEAM_DOWNSTREAM, USER_DOWNSTREAM_LEAD, Role.OWNER),
        (TEAM_DOWNSTREAM, USER_SCIENTIST2, Role.MEMBER),
        (TEAM_QA, USER_VIEWER, Role.MEMBER),
    ]
    for tid, uid, role in memberships:
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.user_id == uid,
                TeamMember.team_id == tid,
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(TeamMember(user_id=uid, team_id=tid, role=role))
    await db.flush()


async def seed_projects(db: AsyncSession):
    await _upsert(
        db, Project, PROJECT_MAB,
        name="mAb Production v2",
        description="Monoclonal antibody production optimization",
        organization_id=ORG_ID,
        owner_type="TEAM",
        owner_id=TEAM_UPSTREAM,
    )
    await _upsert(
        db, Project, PROJECT_VACCINE,
        name="Vaccine Formulation Study",
        description="Novel vaccine formulation research",
        organization_id=ORG_ID,
        owner_type="USER",
        owner_id=USER_DOWNSTREAM_LEAD,
    )


async def seed_permissions(db: AsyncSession):
    """Seed object-level permissions."""
    perms = [
        # Upstream Team → ADMIN on mAb
        (PrincipalType.TEAM, TEAM_UPSTREAM, ObjectType.PROJECT, PROJECT_MAB, PermissionLevel.ADMIN),
        # Downstream Team → VIEW on mAb
        (PrincipalType.TEAM, TEAM_DOWNSTREAM, ObjectType.PROJECT, PROJECT_MAB, PermissionLevel.VIEW),
        # QA → VIEW on both
        (PrincipalType.TEAM, TEAM_QA, ObjectType.PROJECT, PROJECT_MAB, PermissionLevel.VIEW),
        (PrincipalType.TEAM, TEAM_QA, ObjectType.PROJECT, PROJECT_VACCINE, PermissionLevel.VIEW),
        # Lead2 → ADMIN on Vaccine
        (PrincipalType.USER, USER_DOWNSTREAM_LEAD, ObjectType.PROJECT, PROJECT_VACCINE, PermissionLevel.ADMIN),
        # Scientist2 → EDIT on Vaccine
        (PrincipalType.USER, USER_SCIENTIST2, ObjectType.PROJECT, PROJECT_VACCINE, PermissionLevel.EDIT),
    ]
    for pt, pid, ot, oid, level in perms:
        result = await db.execute(
            select(ObjectPermission).where(
                ObjectPermission.principal_type == pt.value,
                ObjectPermission.principal_id == pid,
                ObjectPermission.object_type == ot.value,
                ObjectPermission.object_id == oid,
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(ObjectPermission(
                principal_type=pt.value,
                principal_id=pid,
                object_type=ot.value,
                object_id=oid,
                permission_level=level.value,
            ))
    await db.flush()


async def seed_unit_ops(db: AsyncSession):
    """Seed the unit operation library."""
    unit_ops = [
        {
            "name": "Buffer Preparation",
            "category": "Media Prep",
            "description": "Prepare buffer solution with specified components",
            "param_schema": {
                "type": "object",
                "properties": {
                    "buffer_type": {"type": "string"},
                    "volume_L": {"type": "number"},
                    "pH_target": {"type": "number"},
                },
            },
        },
        {
            "name": "Media Preparation",
            "category": "Media Prep",
            "description": "Prepare cell culture media",
            "param_schema": {
                "type": "object",
                "properties": {
                    "media_type": {"type": "string"},
                    "volume_L": {"type": "number"},
                    "supplements": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "Seeding",
            "category": "Cell Culture",
            "description": "Seed cells into bioreactor or vessel",
            "param_schema": {
                "type": "object",
                "properties": {
                    "cell_density": {"type": "number"},
                    "vessel_type": {"type": "string"},
                    "volume_mL": {"type": "number"},
                },
            },
        },
        {
            "name": "Incubation",
            "category": "Cell Culture",
            "description": "Incubate cells under controlled conditions",
            "param_schema": {
                "type": "object",
                "properties": {
                    "temperature_C": {"type": "number"},
                    "CO2_percent": {"type": "number"},
                    "duration_hours": {"type": "number"},
                    "rpm": {"type": "number"},
                },
            },
        },
        {
            "name": "Cell Counting",
            "category": "Cell Culture",
            "description": "Count cells and assess viability",
            "param_schema": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "dilution_factor": {"type": "number"},
                },
            },
        },
        {
            "name": "Transfection",
            "category": "Cell Culture",
            "description": "Transfect cells with DNA/RNA",
            "param_schema": {
                "type": "object",
                "properties": {
                    "reagent": {"type": "string"},
                    "dna_amount_ug": {"type": "number"},
                    "method": {"type": "string"},
                },
            },
        },
        {
            "name": "Harvest",
            "category": "Cell Culture",
            "description": "Harvest cells from culture vessel",
            "param_schema": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "centrifuge_rcf": {"type": "number"},
                },
            },
        },
        {
            "name": "Centrifugation",
            "category": "Purification",
            "description": "Separate components by centrifugal force",
            "param_schema": {
                "type": "object",
                "properties": {
                    "rcf_g": {"type": "number"},
                    "duration_min": {"type": "number"},
                    "temperature_C": {"type": "number"},
                },
            },
        },
        {
            "name": "Filtration",
            "category": "Purification",
            "description": "Filter solution through membrane",
            "param_schema": {
                "type": "object",
                "properties": {
                    "filter_size_um": {"type": "number"},
                    "filter_type": {"type": "string"},
                    "volume_L": {"type": "number"},
                },
            },
        },
        {
            "name": "Chromatography",
            "category": "Purification",
            "description": "Purify target molecule via chromatography",
            "param_schema": {
                "type": "object",
                "properties": {
                    "column_type": {"type": "string"},
                    "resin": {"type": "string"},
                    "flow_rate_mL_min": {"type": "number"},
                },
            },
        },
        {
            "name": "pH Adjustment",
            "category": "Reaction",
            "description": "Adjust pH of solution",
            "param_schema": {
                "type": "object",
                "properties": {
                    "target_pH": {"type": "number"},
                    "acid_or_base": {"type": "string"},
                },
            },
        },
        {
            "name": "Mixing",
            "category": "Reaction",
            "description": "Mix components together",
            "param_schema": {
                "type": "object",
                "properties": {
                    "speed_rpm": {"type": "number"},
                    "duration_min": {"type": "number"},
                    "temperature_C": {"type": "number"},
                },
            },
        },
        {
            "name": "Sample Collection",
            "category": "Analytics",
            "description": "Collect sample for analysis",
            "param_schema": {
                "type": "object",
                "properties": {
                    "volume_mL": {"type": "number"},
                    "container_type": {"type": "string"},
                    "storage_temp_C": {"type": "number"},
                },
            },
        },
        {
            "name": "Assay",
            "category": "Analytics",
            "description": "Run analytical assay on sample",
            "param_schema": {
                "type": "object",
                "properties": {
                    "assay_type": {"type": "string"},
                    "method": {"type": "string"},
                },
            },
        },
        {
            "name": "Fill",
            "category": "Fill/Finish",
            "description": "Fill product into final containers",
            "param_schema": {
                "type": "object",
                "properties": {
                    "fill_volume_mL": {"type": "number"},
                    "container_type": {"type": "string"},
                    "fill_speed": {"type": "string"},
                },
            },
        },
        {
            "name": "Lyophilization",
            "category": "Fill/Finish",
            "description": "Freeze-dry product",
            "param_schema": {
                "type": "object",
                "properties": {
                    "shelf_temp_C": {"type": "number"},
                    "chamber_pressure_mTorr": {"type": "number"},
                    "duration_hours": {"type": "number"},
                },
            },
        },
        {
            "name": "Visual Inspection",
            "category": "Quality Control",
            "description": "Visually inspect product for defects",
            "param_schema": {
                "type": "object",
                "properties": {
                    "inspection_type": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                },
            },
        },
    ]

    for op_data in unit_ops:
        result = await db.execute(
            select(UnitOpDefinition).where(
                UnitOpDefinition.name == op_data["name"]
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(UnitOpDefinition(**op_data))
    await db.flush()


async def run_seed():
    """Run all seed functions in order."""
    async with AsyncSessionLocal() as db:
        print("Seeding users...")
        await seed_users(db)
        print("Seeding organization...")
        await seed_org(db)
        print("Seeding teams...")
        await seed_teams(db)
        print("Seeding projects...")
        await seed_projects(db)
        print("Seeding permissions...")
        await seed_permissions(db)
        print("Seeding unit operations...")
        await seed_unit_ops(db)

        await db.commit()
        print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(run_seed())

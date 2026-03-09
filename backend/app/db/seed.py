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
    TeamRole,
)
from app.models.science import Project, UnitOpDefinition


# --- Fixed UUIDs for reproducibility ---
ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
ORG_ID_2 = uuid.UUID("10000000-0000-0000-0000-000000000002")

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
    await _upsert(db, Organization, ORG_ID_2, name="Acme Biologics")

    # Org memberships — primary org
    members = [
        (ORG_ID, USER_ADMIN, "ADMIN"),
        (ORG_ID, USER_UPSTREAM_LEAD, "MEMBER"),
        (ORG_ID, USER_DOWNSTREAM_LEAD, "MEMBER"),
        (ORG_ID, USER_SCIENTIST1, "MEMBER"),
        (ORG_ID, USER_SCIENTIST2, "MEMBER"),
        (ORG_ID, USER_VIEWER, "MEMBER"),
        # Second org — admin is a member of both (for org-switching E2E tests)
        (ORG_ID_2, USER_ADMIN, "ADMIN"),
    ]
    for org_id, uid, role in members:
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == uid,
                OrganizationMember.organization_id == org_id,
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(OrganizationMember(
                user_id=uid,
                organization_id=org_id,
                role=role,
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
        (TEAM_UPSTREAM, USER_UPSTREAM_LEAD, TeamRole.LEAD),
        (TEAM_UPSTREAM, USER_SCIENTIST1, TeamRole.MEMBER),
        (TEAM_DOWNSTREAM, USER_DOWNSTREAM_LEAD, TeamRole.LEAD),
        (TEAM_DOWNSTREAM, USER_SCIENTIST2, TeamRole.MEMBER),
        (TEAM_QA, USER_VIEWER, TeamRole.MEMBER),
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
            "description": "Prepare {{volume_L}}L of {{buffer_name}} by dissolving {{components}} in {{solvent}}. Adjust to pH {{pH_target}} (+/- {{pH_tolerance}}) using {{pH_agent}}. Store at {{storage_temp_c}}°C.",
            "param_schema": {
                "type": "object",
                "properties": {
                    "buffer_name": {"type": "string", "title": "Buffer Name", "default": "PBS"},
                    "volume_L": {"type": "number", "title": "Final Volume (L)", "default": 10},
                    "components": {"type": "string", "title": "Components", "default": "NaCl, KCl, Na2HPO4, KH2PO4"},
                    "concentration_mM": {"type": "number", "title": "Target Concentration (mM)", "default": 137},
                    "pH_target": {"type": "number", "title": "Target pH", "default": 7.4},
                    "pH_tolerance": {"type": "number", "title": "pH Tolerance (+/-)", "default": 0.1},
                    "pH_agent": {"type": "string", "title": "pH Adjustment Agent", "default": "NaOH / HCl"},
                    "solvent": {"type": "string", "title": "Solvent", "default": "WFI (Water for Injection)"},
                    "storage_temp_c": {"type": "number", "title": "Storage Temperature (C)", "default": 4},
                },
            },
        },
        {
            "name": "Media Preparation",
            "category": "Media Prep",
            "description": "Reconstitute {{volume_L}}L of {{media_name}} using {{basal_medium}}. Add {{supplements}}, adjust to pH {{pH_target}}, verify osmolality at {{osmolality_mOsm}} mOsm/kg. Sterile filter: {{filter_after}}. Store at {{storage_temp_c}}°C.",
            "param_schema": {
                "type": "object",
                "properties": {
                    "media_name": {"type": "string", "title": "Media Name", "default": "DMEM/F-12"},
                    "volume_L": {"type": "number", "title": "Final Volume (L)", "default": 10},
                    "basal_medium": {"type": "string", "title": "Basal Medium", "default": "DMEM/F-12 powder"},
                    "supplements": {"type": "string", "title": "Supplements", "default": "10% FBS, 1% L-glutamine, 1% Pen/Strep"},
                    "glucose_g_L": {"type": "number", "title": "Glucose Concentration (g/L)", "default": 4.5},
                    "pH_target": {"type": "number", "title": "Target pH", "default": 7.2},
                    "osmolality_mOsm": {"type": "number", "title": "Target Osmolality (mOsm/kg)", "default": 300},
                    "filter_after": {"type": "boolean", "title": "Sterile Filter After Prep", "default": True},
                    "storage_temp_c": {"type": "number", "title": "Storage Temperature (C)", "default": 4},
                },
            },
        },
        {
            "name": "Seeding",
            "category": "Cell Culture",
            "description": "Seed cells at {{cell_density}} cells/mL into {{vessel_type}} with {{volume_mL}}mL working volume.",
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
            "description": "Incubate at {{temperature_C}}°C with {{CO2_percent}}% CO2 at {{rpm}} RPM for {{duration_hours}} hours.",
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
            "description": "Count cells using {{method}} method with {{dilution_factor}}x dilution factor.",
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
            "description": "Transfect cells using {{reagent}} with {{dna_amount_ug}}ug DNA via {{method}} method.",
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
            "description": "Harvest cells using {{method}} method, centrifuge at {{centrifuge_rcf}}xg.",
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
            "description": "Centrifuge at {{rcf_g}}xg for {{duration_min}} minutes at {{temperature_C}}°C.",
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
            "description": "Filter {{volume_L}}L through {{filter_type}} membrane ({{filter_size_um}}um pore size).",
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
            "description": "Purify using {{column_type}} column with {{resin}} resin at {{flow_rate_mL_min}} mL/min flow rate.",
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
            "description": "Adjust solution to pH {{target_pH}} using {{acid_or_base}}.",
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
            "description": "Mix at {{speed_rpm}} RPM for {{duration_min}} minutes at {{temperature_C}}°C.",
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
            "description": "Collect {{volume_mL}}mL sample into {{container_type}}, store at {{storage_temp_C}}°C.",
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
            "description": "Run {{assay_type}} assay using {{method}} method.",
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
            "description": "Fill {{fill_volume_mL}}mL into {{container_type}} at {{fill_speed}} speed.",
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
            "description": "Lyophilize at {{shelf_temp_C}}°C shelf temperature, {{chamber_pressure_mTorr}} mTorr chamber pressure for {{duration_hours}} hours.",
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
            "description": "Perform {{inspection_type}} visual inspection. Acceptance criteria: {{acceptance_criteria}}.",
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

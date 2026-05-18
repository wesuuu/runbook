"""Centralized seed data for the Batchrite application.

Run via: python -m app.db.seed (from backend directory)

Seeds a complete demo organization with users, teams, projects,
permissions, and unit operations. All functions are idempotent
(check-before-insert).
"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    Team,
    TeamMember,
    TeamRole,
    User,
)
from app.models.science import Project
from app.models.templates import DocumentTemplate, TemplateType
from app.services.protocols.template_seeder import seed_system_templates

# --- Fixed UUIDs for reproducibility ---
ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
ORG_ID_2 = uuid.UUID("10000000-0000-0000-0000-000000000002")

USER_SYSTEM = uuid.UUID("00000000-0000-0000-0000-000000000000")
USER_ADMIN = uuid.UUID("20000000-0000-0000-0000-000000000001")
USER_UPSTREAM_LEAD = uuid.UUID("20000000-0000-0000-0000-000000000002")
USER_DOWNSTREAM_LEAD = uuid.UUID("20000000-0000-0000-0000-000000000003")
USER_SCIENTIST1 = uuid.UUID("20000000-0000-0000-0000-000000000004")
USER_SCIENTIST2 = uuid.UUID("20000000-0000-0000-0000-000000000005")
USER_VIEWER = uuid.UUID("20000000-0000-0000-0000-000000000006")

USER_NEWBIE = uuid.UUID("20000000-0000-0000-0000-0000000000ff")
ORG_ID_NEWBIE = uuid.UUID("10000000-0000-0000-0000-0000000000ff")
PROJECT_NEWBIE = uuid.UUID("40000000-0000-0000-0000-0000000000ff")

TEAM_UPSTREAM = uuid.UUID("30000000-0000-0000-0000-000000000001")
TEAM_DOWNSTREAM = uuid.UUID("30000000-0000-0000-0000-000000000002")
TEAM_QA = uuid.UUID("30000000-0000-0000-0000-000000000003")

PROJECT_MAB = uuid.UUID("40000000-0000-0000-0000-000000000001")
PROJECT_VACCINE = uuid.UUID("40000000-0000-0000-0000-000000000002")

DEFAULT_PASSWORD = hash_password("password123")


async def _upsert(db: AsyncSession, model, pk_id: uuid.UUID, **kwargs):
    """Insert if not exists (by PK). Returns the object."""
    result = await db.execute(select(model).where(model.id == pk_id))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    obj = model(id=pk_id, **kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def seed_users(db: AsyncSession):
    # System actor — referenced by audit entries from webhook/background code
    # that has no authenticated user. Must exist so `audit_logs.actor_id` FK
    # resolves; never intended to log in (hashed_password is unusable).
    await _upsert(
        db,
        User,
        USER_SYSTEM,
        email="system@batchrite.internal",
        hashed_password="!system-locked!",
        full_name="System",
        email_verified=True,
        is_active=False,
    )

    users = [
        (USER_ADMIN, "admin@bioprocess.com", "Admin User"),
        (USER_UPSTREAM_LEAD, "upstream.lead@bioprocess.com", "Upstream Lead"),
        (USER_DOWNSTREAM_LEAD, "downstream.lead@bioprocess.com", "Downstream Lead"),
        (USER_SCIENTIST1, "scientist1@bioprocess.com", "Scientist One"),
        (USER_SCIENTIST2, "scientist2@bioprocess.com", "Scientist Two"),
        (USER_VIEWER, "viewer@bioprocess.com", "Viewer User"),
    ]
    for uid, email, name in users:
        user = await _upsert(
            db,
            User,
            uid,
            email=email,
            hashed_password=DEFAULT_PASSWORD,
            full_name=name,
            selected_org_id=ORG_ID,
            email_verified=True,
        )
        # Backfill existing seed users that lack selected_org_id / verification
        if user.selected_org_id is None:
            user.selected_org_id = ORG_ID
        if not user.email_verified:
            user.email_verified = True


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
            db.add(
                OrganizationMember(
                    user_id=uid,
                    organization_id=org_id,
                    roles=sorted({"MEMBER", role}),
                )
            )
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
        db,
        Project,
        PROJECT_MAB,
        name="mAb Production v2",
        description="Monoclonal antibody production optimization",
        organization_id=ORG_ID,
        owner_type="TEAM",
        owner_id=TEAM_UPSTREAM,
    )
    await _upsert(
        db,
        Project,
        PROJECT_VACCINE,
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
        (
            PrincipalType.TEAM,
            TEAM_UPSTREAM,
            ObjectType.PROJECT,
            PROJECT_MAB,
            PermissionLevel.ADMIN,
        ),
        # Downstream Team → VIEW on mAb
        (
            PrincipalType.TEAM,
            TEAM_DOWNSTREAM,
            ObjectType.PROJECT,
            PROJECT_MAB,
            PermissionLevel.VIEW,
        ),
        # QA → VIEW on both
        (
            PrincipalType.TEAM,
            TEAM_QA,
            ObjectType.PROJECT,
            PROJECT_MAB,
            PermissionLevel.VIEW,
        ),
        (
            PrincipalType.TEAM,
            TEAM_QA,
            ObjectType.PROJECT,
            PROJECT_VACCINE,
            PermissionLevel.VIEW,
        ),
        # Lead2 → ADMIN on Vaccine
        (
            PrincipalType.USER,
            USER_DOWNSTREAM_LEAD,
            ObjectType.PROJECT,
            PROJECT_VACCINE,
            PermissionLevel.ADMIN,
        ),
        # Scientist2 → EDIT on Vaccine
        (
            PrincipalType.USER,
            USER_SCIENTIST2,
            ObjectType.PROJECT,
            PROJECT_VACCINE,
            PermissionLevel.EDIT,
        ),
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
            db.add(
                ObjectPermission(
                    principal_type=pt.value,
                    principal_id=pid,
                    object_type=ot.value,
                    object_id=oid,
                    permission_level=level.value,
                )
            )
    await db.flush()


async def seed_library_subscriptions(db: AsyncSession):
    """Subscribe every existing organization to every default library."""
    from pathlib import Path

    from sqlalchemy import select

    from app.models.iam import Organization
    from app.services.science import library_registry

    if not library_registry.list_libraries():
        # Lifespan didn't run (we're called from a CLI script). Bootstrap.
        library_registry.register_source(
            library_registry.BundledJSONSource(
                Path(__file__).resolve().parents[1] / "data/unit_op_libraries"
            )
        )
        await library_registry.reload_libraries()

    org_q = await db.execute(select(Organization))
    for org in org_q.scalars():
        await library_registry.subscribe_default_libraries(db, org.id)


async def seed_newbie_user(db: AsyncSession):
    """Create a fresh, email-verified user with an empty tour_state.

    Used for manually testing the F-0015 onboarding tour. The user has
    their own org and a single "My First Project" — matching what a real
    new signup looks like, so the welcome modal auto-opens on login.
    """
    # Fresh org just for this user
    await _upsert(db, Organization, ORG_ID_NEWBIE, name="Newbie's Organization")

    user = await _upsert(
        db,
        User,
        USER_NEWBIE,
        email="newbie@bioprocess.com",
        hashed_password=DEFAULT_PASSWORD,
        full_name="Newbie Tester",
        selected_org_id=ORG_ID_NEWBIE,
        email_verified=True,
    )
    # Always reset tour_state so repeated seeds give a clean test experience
    user.tour_state = {}

    # Org membership (ADMIN)
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == USER_NEWBIE,
            OrganizationMember.organization_id == ORG_ID_NEWBIE,
        )
    )
    if result.scalar_one_or_none() is None:
        db.add(
            OrganizationMember(
                user_id=USER_NEWBIE,
                organization_id=ORG_ID_NEWBIE,
                roles=["MEMBER", "ADMIN"],
            )
        )

    # Seed a single starter project (mirrors what auth/register does)
    await _upsert(
        db,
        Project,
        PROJECT_NEWBIE,
        name="My First Project",
        description="Created for you — rename or delete as you like.",
        organization_id=ORG_ID_NEWBIE,
    )

    await db.flush()


async def seed_document_templates(db: AsyncSession):
    """Seed system-wide default document templates."""
    from app.services.core.file_storage import FileStorageService

    # Copy template files to storage
    storage = FileStorageService()
    seed_system_templates(str(storage.storage_root))

    # Define system templates
    templates = [
        {
            "filename": "sop_default.docx",
            "name": "Standard Operating Procedure",
            "template_type": TemplateType.SOP,
            "description": "Default SOP template for generating procedure documents",
        },
        {
            "filename": "batch_record_default.docx",
            "name": "Batch Record",
            "template_type": TemplateType.BATCH_RECORD,
            "description": "Default batch record template for documenting batches",
        },
    ]

    for template_info in templates:
        # Check if already exists
        result = await db.execute(
            select(DocumentTemplate).where(
                DocumentTemplate.is_system == True,
                DocumentTemplate.template_type == template_info["template_type"],
            )
        )
        if result.scalar_one_or_none() is not None:
            continue

        # Get file info
        filename = template_info["filename"]
        file_path = f"system/document_templates/{filename}"
        full_path = storage.storage_root / file_path
        file_size = full_path.stat().st_size if full_path.exists() else 0

        # Create template record
        template = DocumentTemplate(
            org_id=None,  # System-wide, not org-specific
            project_id=None,
            uploaded_by_id=None,
            name=template_info["name"],
            description=template_info["description"],
            template_type=template_info["template_type"],
            file_path=file_path,
            original_filename=filename,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=file_size,
            is_system=True,
            variables={},
        )
        db.add(template)

    await db.flush()


async def run_seed():
    """Run all seed functions in order."""
    async with AsyncSessionLocal() as db:
        print("Seeding users...")
        await seed_users(db)
        print("Seeding organization...")
        await seed_org(db)
        print("Seeding document templates...")
        await seed_document_templates(db)
        print("Seeding teams...")
        await seed_teams(db)
        print("Seeding projects...")
        await seed_projects(db)
        print("Seeding permissions...")
        await seed_permissions(db)
        print("Seeding library subscriptions...")
        await seed_library_subscriptions(db)
        print("Seeding newbie user...")
        await seed_newbie_user(db)

        await db.commit()
        print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(run_seed())

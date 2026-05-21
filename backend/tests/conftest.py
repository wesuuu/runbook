import os

os.environ["BATCHRITE_AUTH_ENABLED"] = "true"

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.equipment import Equipment
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    Team,
    TeamMember,
    User,
)
from app.models.library import Document, DocumentStatus
from app.models.projects import Project
from app.models.protocols import Protocol, ProtocolRole
from app.models.runs import Run, RunOutcome, RunStatus
from app.models.templates import DocumentTemplate  # noqa: F401
from app.services.billing import stripe_client as _stripe_client

TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_test"
)


def pytest_addoption(parser):
    parser.addoption(
        "--write-artifacts",
        action="store_true",
        default=False,
        help=(
            "Write rendered .docx and .pdf artifacts into "
            "tests/fixtures/template-permutations/rendered/ for side-by-side "
            "review."
        ),
    )


@pytest.fixture
def write_artifacts(request):
    return bool(request.config.getoption("--write-artifacts"))


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _seed_library_registry():
    """Load bundled libraries once for the test session.

    Mirrors what FastAPI lifespan does in production. Tests that need
    different sources can call library_registry._reset_for_tests() and
    register their own (then re-register/reload to restore).
    """
    from pathlib import Path

    from app.services.protocols import library_registry as lr

    lr._reset_for_tests()
    lr.register_source(
        lr.BundledJSONSource(
            Path(__file__).resolve().parents[1] / "app/data/unit_op_libraries"
        )
    )
    await lr.reload_libraries()
    yield


@pytest.fixture(autouse=True)
def _reset_chat_agent_cache():
    from app.services.ai.chat_agent import _reset_cache_for_tests

    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


@pytest.fixture(autouse=True)
def _disable_stripe_globally(monkeypatch):
    """Ensure Stripe is unconfigured for all tests by default.

    Tests that need Stripe (e.g. billing integration tests) opt-in by
    injecting their own fake via stripe_client.set_fake_client() and
    monkeypatching the settings keys — see configured_fake_stripe.
    This fixture prevents real Stripe API calls caused by keys present
    in local .env / settings.yaml.
    """
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", "")
    _stripe_client._reset_cache()
    yield
    _stripe_client._reset_cache()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Drop and recreate public schema to cleanly remove all tables
        # (avoids FK constraint name mismatches from Alembic vs ORM)
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # Add tsvector generated column (not managed by SQLAlchemy ORM)
        await conn.execute(
            text(
                """
            ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
            )
        )
        await conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS ix_chunk_search_vector
            ON document_chunks USING gin (search_vector)
        """
            )
        )
        # System user referenced by webhook/background audit entries.
        # Mirrors backend/app/db/seed.py::USER_SYSTEM; required here because
        # the test DB is built via create_all, not Alembic migrations.
        await conn.execute(
            text(
                """
            INSERT INTO users (id, email, full_name, hashed_password,
                               email_verified, is_active, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000000',
                    'system@batchrite.internal', 'System',
                    '!system-locked!', true, false, now(), now())
            ON CONFLICT (id) DO NOTHING
        """
            )
        )
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """Per-test session that wraps everything in a SAVEPOINT.

    The outer connection starts a real transaction, and the session
    uses nested transactions (SAVEPOINTs). Any commit() calls inside
    endpoints hit the SAVEPOINT, not the real transaction. At teardown,
    we rollback the outer transaction, undoing everything.
    """
    conn = await test_engine.connect()
    txn = await conn.begin()

    session = AsyncSession(bind=conn, expire_on_commit=False)

    # Make session.commit() use SAVEPOINTs instead of real commits
    @pytest_asyncio.fixture(autouse=True)
    async def _nested():
        pass

    # Override begin_nested to handle commits properly
    async def _begin_nested():
        return conn.begin_nested()

    # send_message opens a separate `AsyncSessionLocal()` for post-LLM writes
    # so production chat is resilient to connections killed during long
    # cloud-LLM round-trips (see app/services/ai/send_message.py). In tests,
    # the fixture's outer transaction is uncommitted, so a brand-new session
    # can't see fixture data and FK lookups fail. Bind the writer factory to
    # the SAME connection used by `db_session` for the duration of the test.
    import importlib

    _send_message_module = importlib.import_module("app.services.ai.send_message")

    test_writer_factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    real_factory = _send_message_module.AsyncSessionLocal
    _send_message_module.AsyncSessionLocal = test_writer_factory

    try:
        yield session
    finally:
        _send_message_module.AsyncSessionLocal = real_factory
        await session.close()
        await txn.rollback()
        await conn.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --- Auth fixtures ---


@pytest_asyncio.fixture
async def test_org(db_session) -> Organization:
    org = Organization(name="Test Org")
    db_session.add(org)
    await db_session.flush()
    # Mirror production: every org auto-subscribes to default libraries.
    from app.services.protocols import library_registry

    if library_registry.list_libraries():  # registry seeded by app startup
        await library_registry.subscribe_default_libraries(db_session, org.id)
    # Mirror production: every new org gets a default site.
    from app.services.core.audit import SYSTEM_ACTOR_ID
    from app.services.sites.defaults import ensure_default_site

    await ensure_default_site(db_session, org.id, actor_id=SYSTEM_ACTOR_ID)
    return org


@pytest_asyncio.fixture
async def test_user(db_session, test_org) -> User:
    user = User(
        email="testuser@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Test User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user, test_org) -> dict:
    token = create_access_token(
        test_user.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_org(db_session) -> Organization:
    """A separate org for the second user so they don't collide with test_org."""
    org = Organization(name="Second Org")
    db_session.add(org)
    await db_session.flush()
    from app.services.protocols import library_registry

    if library_registry.list_libraries():
        await library_registry.subscribe_default_libraries(db_session, org.id)
    return org


@pytest_asyncio.fixture
async def second_user(db_session, second_org) -> User:
    user = User(
        email="second@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Second User",
        selected_org_id=second_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=second_org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def second_auth_headers(second_user, second_org) -> dict:
    token = create_access_token(
        second_user.id,
        org_id=second_org.id,
        subscription_tier=second_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_team(db_session, test_org) -> Team:
    team = Team(name="Test Team", organization_id=test_org.id)
    db_session.add(team)
    await db_session.flush()
    return team


@pytest_asyncio.fixture
async def test_project(db_session, test_org, test_user) -> Project:
    project = Project(
        name="Test Project",
        organization_id=test_org.id,
        slug="test-project",
        owner_type="USER",
        owner_id=test_user.id,
        settings={"permissions_enabled": True},
    )
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=project.id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    await db_session.flush()
    return project


# ── async_session alias ──────────────────────────────────────────────
# Some tests (heartbeat watchdog, endpoint) were written against the
# `async_session` fixture name.  This alias keeps them working without
# touching the canonical `db_session` fixture.


@pytest_asyncio.fixture
async def async_session(db_session: AsyncSession) -> AsyncSession:
    """Alias for db_session — used by heartbeat / watchdog tests."""
    return db_session


# ── fresh_document / extracted_document ──────────────────────────────
# Used by test_library_docling.py integration tests.


@pytest_asyncio.fixture
async def fresh_document(db_session: AsyncSession, test_org, test_user) -> Document:
    """A Document row with status=UPLOADED and no stored_markdown."""
    from app.models.library import RefinementStatus

    doc = Document(
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="Fresh Doc",
        slug="fresh-doc",
        original_filename="fresh.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_path="uploads/fresh.pdf",
        status=DocumentStatus.UPLOADED.value,
        stored_markdown=None,
        refinement_status=RefinementStatus.NOT_REQUIRED.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER.value,
            principal_id=test_user.id,
            object_type=ObjectType.DOCUMENT.value,
            object_id=doc.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    await db_session.flush()
    return doc


@pytest_asyncio.fixture
async def extracted_document(db_session: AsyncSession, test_org, test_user) -> Document:
    """A Document row with status=AWAITING_REFINEMENT and stored markdown."""
    from app.models.library import RefinementStatus

    doc = Document(
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="Extracted Doc",
        slug="extracted-doc",
        original_filename="extracted.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_path="uploads/extracted.pdf",
        status=DocumentStatus.AWAITING_REFINEMENT.value,
        stored_markdown="# Heading\n\nBody\n",
        refinement_status=RefinementStatus.PENDING.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER.value,
            principal_id=test_user.id,
            object_type=ObjectType.DOCUMENT.value,
            object_id=doc.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    await db_session.flush()
    return doc


# ── seed_document_extracting ─────────────────────────────────────────


@pytest.fixture
def make_equipment(db_session, test_org):
    async def _factory(*, site_id, name="Eq"):
        from app.models.equipment import Equipment

        e = Equipment(organization_id=test_org.id, name=name, site_id=site_id)
        db_session.add(e)
        await db_session.commit()
        await db_session.refresh(e)
        return e

    return _factory


@pytest_asyncio.fixture
async def seed_document_extracting(db_session: AsyncSession) -> Document:
    """Yield a Document row in EXTRACTING status.

    Creates the minimum required foreign-key rows (Organization + User)
    inline so this fixture is self-contained and can be used by any unit
    test that needs an active extraction row.
    """
    org = Organization(name=f"hb-test-org-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"hb-{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="!locked!",
        full_name="Heartbeat Test User",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    doc = Document(
        org_id=org.id,
        uploaded_by_id=user.id,
        title="Heartbeat Test Doc",
        slug=f"heartbeat-test-doc-{uuid.uuid4().hex[:8]}",
        original_filename="test.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_path="uploads/test.pdf",
        status=DocumentStatus.EXTRACTING.value,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest.fixture
async def sample_site(db_session, test_org, test_user):
    from app.schemas.sites import SiteCreate
    from app.services.sites import crud as sites_crud

    return await sites_crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Sample Site"),
        actor_id=test_user.id,
    )


@pytest.fixture
async def other_org_site(db_session, second_org, second_user):
    from app.schemas.sites import SiteCreate
    from app.services.sites import crud as sites_crud

    return await sites_crud.create_site(
        db_session,
        org_id=second_org.id,
        payload=SiteCreate(name="Other Org Site"),
        actor_id=second_user.id,
    )


@pytest.fixture
async def sample_equipment(db_session, test_org, test_user, sample_site):
    from app.models.equipment import Equipment

    eq = Equipment(
        organization_id=test_org.id,
        name="Sample Equipment",
        site_id=sample_site.id,
        created_by_id=test_user.id,
    )
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


@pytest.fixture
async def sample_equipment_attachment(db_session, sample_equipment, test_user):
    from app.models.equipment import EquipmentAttachment

    att = EquipmentAttachment(
        equipment_id=sample_equipment.id,
        file_path=(
            f"{sample_equipment.organization_id}/equipment/"
            f"{sample_equipment.id}/test.pdf"
        ),
        original_filename="test.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        uploaded_by_id=test_user.id,
    )
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)
    return att


# ── Sites role-gate fixtures ─────────────────────────────────────────────────


def _make_bearer_client(db_session, user, org):
    """Build an AsyncClient pre-loaded with a Bearer token for `user`.

    Each call produces an independent client with its own token so tests that
    request two authed clients (e.g. admin + member) in the same function
    don't clobber each other's headers.  The db_session override is idempotent
    (all roles share the same session); cleanup is left to the caller.
    """
    from httpx import ASGITransport, AsyncClient

    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=True,
    )

    async def override_get_db():
        yield db_session

    # Set the override every time — safe because it's always the same session.
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def authed_admin_client(db_session, test_user, test_org):
    """test_user is already ADMIN+MEMBER of test_org."""
    async with _make_bearer_client(db_session, test_user, test_org) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def member_user(db_session, test_org) -> User:
    user = User(
        email="member-only@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Member User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def authed_member_client(db_session, member_user, test_org):
    async with _make_bearer_client(db_session, member_user, test_org) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def site_manager_user(db_session, test_org) -> User:
    user = User(
        email="site-mgr@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Site Manager",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER", "SITE_MANAGER"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def authed_site_manager_client(db_session, site_manager_user, test_org):
    async with _make_bearer_client(db_session, site_manager_user, test_org) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def managed_site(db_session, test_org, test_user, site_manager_user):
    """A site that `site_manager_user` has a grant on."""
    from app.schemas.sites import SiteCreate
    from app.services.sites import crud as sites_crud
    from app.services.sites import grants as sites_grants

    site = await sites_crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Managed Site"),
        actor_id=test_user.id,
    )
    await sites_grants.grant_site_manager(
        db_session,
        site=site,
        user_id=site_manager_user.id,
        granted_by_id=test_user.id,
    )
    return site


@pytest_asyncio.fixture
async def unmanaged_site(db_session, test_org, test_user):
    """A site that nobody has a grant on (other than ADMINs)."""
    from app.schemas.sites import SiteCreate
    from app.services.sites import crud as sites_crud

    return await sites_crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Unmanaged Site"),
        actor_id=test_user.id,
    )


@pytest_asyncio.fixture
async def grantee_user(db_session, test_org) -> User:
    """A bare MEMBER eligible to be granted a SITE_MANAGER role on a site."""
    user = User(
        email="grantee@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Grantee User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER", "SITE_MANAGER"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def default_site_id(db_session, test_org) -> str:
    """ID of the auto-seeded Default Site for test_org."""
    from app.services.sites.crud import list_sites
    from app.services.sites.defaults import DEFAULT_SITE_NAME

    sites = await list_sites(db_session, test_org.id)
    for s in sites:
        if s.name == DEFAULT_SITE_NAME:
            return str(s.id)
    raise RuntimeError("Default Site not seeded for test_org")


@pytest_asyncio.fixture
async def member_owned_equipment_id(
    db_session, test_org, test_user, managed_site
) -> str:
    """Equipment on `managed_site` (which `site_manager_user` has a grant on).

    Used by tests where SITE_MANAGER with grant should be authorized for
    restricted edits, but the equipment was created by any member."""
    from app.models.equipment import Equipment

    eq = Equipment(
        organization_id=test_org.id,
        name="Member Owned",
        site_id=managed_site.id,
        created_by_id=test_user.id,
    )
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return str(eq.id)


@pytest_asyncio.fixture
async def equipment_on_unmanaged_site_id(
    db_session, test_org, test_user, unmanaged_site
) -> str:
    """Equipment on a site nobody has a grant on (other than ADMINs)."""
    from app.models.equipment import Equipment

    eq = Equipment(
        organization_id=test_org.id,
        name="Unmanaged Site Equip",
        site_id=unmanaged_site.id,
        created_by_id=test_user.id,
    )
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return str(eq.id)


@pytest_asyncio.fixture
async def archived_equipment_id(db_session, test_org, test_user, managed_site) -> str:
    """An archived equipment row to test the read-only guard."""
    from datetime import datetime, timezone

    from app.models.equipment import Equipment

    eq = Equipment(
        organization_id=test_org.id,
        name="Archived",
        site_id=managed_site.id,
        created_by_id=test_user.id,
        archived_at=datetime.now(timezone.utc),
        archived_by_id=test_user.id,
    )
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return str(eq.id)


# ── F-0087 GLP fixtures ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def glp_org(test_org) -> Organization:
    """Alias for test_org. GLP capability is currently org-agnostic; this
    fixture exists so tests can express the intent and so future tier/flag
    gating has a single attachment point."""
    return test_org


def _make_glp_user(
    email: str,
    full_name: str,
    signature_basename: str,
    glp_org: Organization,
) -> User:
    return User(
        email=email,
        hashed_password=hash_password("testpass"),
        full_name=full_name,
        selected_org_id=glp_org.id,
        email_verified=True,
        signature_full_path=f"signatures/default/{signature_basename}.png",
    )


@pytest_asyncio.fixture
async def study_director_user(db_session, glp_org) -> User:
    user = _make_glp_user(
        "studydirector@example.com", "Dana Director", "dana_director", glp_org
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=glp_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def qau_user(db_session, glp_org) -> User:
    user = _make_glp_user("qau@example.com", "Quinn Auditor", "quinn_auditor", glp_org)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=glp_org.id,
            roles=["MEMBER", "QAU"],
        )
    )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def operator_user(db_session, glp_org) -> User:
    user = _make_glp_user(
        "operator@example.com", "Oscar Operator", "oscar_operator", glp_org
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=glp_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()
    return user


def _glp_protocol_graph(
    sd_lane_role_id, op_lane_role_id, sd_user_id, qau_user_id
) -> dict:
    sd_lane = f"lane-{sd_lane_role_id}"
    op_lane = f"lane-{op_lane_role_id}"
    return {
        "layout": "horizontal",
        "handleOrientation": "horizontal",
        "nodes": [
            {"id": "ps", "type": "processStart", "data": {}},
            {
                "id": sd_lane,
                "type": "swimLane",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "Study Director",
                    "roleId": str(sd_lane_role_id),
                    "orientation": "horizontal",
                },
                "style": "width: 800px; height: 200px;",
            },
            {
                "id": op_lane,
                "type": "swimLane",
                "position": {"x": 0, "y": 220},
                "data": {
                    "label": "Operator",
                    "roleId": str(op_lane_role_id),
                    "orientation": "horizontal",
                },
                "style": "width: 800px; height: 200px;",
            },
            {
                "id": "u0",
                "type": "unitOp",
                "parentId": sd_lane,
                "position": {"x": 20, "y": 60},
                "data": {"label": "Review", "params": {}},
            },
            {
                "id": "u1",
                "type": "unitOp",
                "parentId": op_lane,
                "position": {"x": 20, "y": 60},
                "data": {"label": "Buffer Mix", "params": {}},
            },
            {
                "id": "u2",
                "type": "unitOp",
                "parentId": op_lane,
                "position": {"x": 220, "y": 60},
                "data": {"label": "Seeding", "params": {}},
            },
        ],
        "edges": [
            {"id": "e0", "source": "ps", "target": "u0"},
            {"id": "e1", "source": "u0", "target": "u1"},
            {"id": "e2", "source": "u1", "target": "u2"},
        ],
        "glpSettings": {
            "glp_enabled": True,
            "require_study_director": True,
            "require_qau": True,
            "study_title": "Test GLP Study",
            "sponsor_name": "Acme Pharma",
            "study_director_id": str(sd_user_id),
            "qau_id": str(qau_user_id),
            "operator_attestation_text": "I performed this run accurately.",
            "study_director_attestation_text": (
                "I attest this study is in compliance with the protocol."
            ),
            "qau_attestation_text": ("I have audited this study for GLP compliance."),
            "step_attestation_text": "Step recorded under GLP.",
        },
    }


@pytest_asyncio.fixture
async def glp_protocol(
    db_session,
    glp_org,
    test_project,
    study_director_user,
    qau_user,
) -> Protocol:
    import uuid

    sd_role_id = uuid.uuid4()
    op_role_id = uuid.uuid4()

    proto = Protocol(
        name="GLP Test Protocol",
        project_id=test_project.id,
        slug="glp-test-protocol",
        owner_org_id=glp_org.id,
        status="DRAFT",
        version_number=1,
        created_by_id=study_director_user.id,
        graph=_glp_protocol_graph(
            sd_role_id, op_role_id, study_director_user.id, qau_user.id
        ),
    )
    db_session.add(proto)
    await db_session.flush()

    db_session.add_all(
        [
            ProtocolRole(
                id=sd_role_id,
                protocol_id=proto.id,
                name="Study Director",
                sort_order=0,
            ),
            ProtocolRole(
                id=op_role_id,
                protocol_id=proto.id,
                name="Operator",
                sort_order=1,
            ),
        ]
    )
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def glp_run_planned(db_session, test_project, glp_protocol) -> Run:
    run = Run(
        name="GLP Run (planned)",
        project_id=test_project.id,
        slug="glp-run-planned",
        protocol_id=glp_protocol.id,
        status=RunStatus.PLANNED,
        graph=dict(glp_protocol.graph),
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def glp_run_active(db_session, test_project, glp_protocol, operator_user) -> Run:
    from datetime import datetime, timezone

    run = Run(
        name="GLP Run (active)",
        project_id=test_project.id,
        slug="glp-run-active",
        protocol_id=glp_protocol.id,
        status=RunStatus.ACTIVE,
        graph=dict(glp_protocol.graph),
        execution_data={},
        notes=[],
        attachments=[],
        started_by_id=operator_user.id,
        created_by_id=operator_user.id,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def glp_run_completed(
    db_session,
    test_project,
    glp_protocol,
    operator_user,
    study_director_user,
    qau_user,
) -> Run:
    from datetime import datetime, timedelta, timezone

    started = datetime.now(timezone.utc) - timedelta(hours=2)
    run = Run(
        name="GLP Run (completed)",
        project_id=test_project.id,
        slug="glp-run-completed",
        protocol_id=glp_protocol.id,
        status=RunStatus.COMPLETED,
        graph=dict(glp_protocol.graph),
        execution_data={},
        notes=[],
        attachments=[],
        started_by_id=operator_user.id,
        created_by_id=operator_user.id,
        started_at=started,
        completed_at=datetime.now(timezone.utc),
        outcome=RunOutcome.COMPLETED_NORMAL.value,
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def fresh_equipment(db_session, glp_org, default_site_id) -> Equipment:
    """Equipment whose next_calibration_date is comfortably in the future."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
        site_id=default_site_id,
        name="Fresh Balance",
        equipment_type="balance",
        serial_number="BAL-FRESH-001",
        last_calibration_date=date.today() - timedelta(days=30),
        next_calibration_date=date.today() + timedelta(days=180),
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest_asyncio.fixture
async def imminent_equipment(db_session, glp_org, default_site_id) -> Equipment:
    """Equipment whose calibration expires within the IMMINENT window."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
        site_id=default_site_id,
        name="Imminent pH Meter",
        equipment_type="ph_meter",
        serial_number="PH-IMM-001",
        last_calibration_date=date.today() - timedelta(days=358),
        next_calibration_date=date.today() + timedelta(days=7),
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest_asyncio.fixture
async def expired_equipment(db_session, glp_org, default_site_id) -> Equipment:
    """Equipment whose calibration has lapsed."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
        site_id=default_site_id,
        name="Expired Bioreactor",
        equipment_type="bioreactor",
        serial_number="BR-EXP-001",
        last_calibration_date=date.today() - timedelta(days=395),
        next_calibration_date=date.today() - timedelta(days=30),
    )
    db_session.add(eq)
    await db_session.flush()
    return eq

import os

os.environ["BATCHRITE_AUTH_ENABLED"] = "true"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.pool import NullPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            OrganizationMember, PermissionLevel, PrincipalType,
                            Team, TeamMember, User)
from app.models.science import Project
from app.models.templates import DocumentTemplate  # noqa: F401
from app.services.billing import stripe_client as _stripe_client

TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_test"
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _seed_library_registry():
    """Load bundled libraries once for the test session.

    Mirrors what FastAPI lifespan does in production. Tests that need
    different sources can call library_registry._reset_for_tests() and
    register their own (then re-register/reload to restore).
    """
    from pathlib import Path

    from app.services.science import library_registry as lr

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

    yield session

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
    from app.services.science import library_registry

    if library_registry.list_libraries():  # registry seeded by app startup
        await library_registry.subscribe_default_libraries(db_session, org.id)
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
    from app.services.science import library_registry

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

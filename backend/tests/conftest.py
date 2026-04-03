import os

os.environ["BATCHRITE_AUTH_ENABLED"] = "true"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.core.security import hash_password, create_access_token
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
)
from app.models.science import Project
from app.models.templates import DocumentTemplate  # noqa: F401

TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_test"
)


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
        await conn.execute(text("""
            ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_chunk_search_vector
            ON document_chunks USING gin (search_vector)
        """))
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
            role="ADMIN",
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
            role="ADMIN",
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

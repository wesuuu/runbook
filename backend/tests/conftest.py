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
from app.models.science import (Equipment, Project, Protocol, ProtocolRole,
                                Run, RunOutcome, RunStatus)
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


# --- GLP fixtures (F-0087 Task 41.0) ---------------------------------------
#
# Shared fixtures for GLP (21 CFR Part 58) tests. Composes on test_org /
# db_session / test_project. Per-fixture defaults are kept minimal — only
# what's needed to satisfy CHECK constraints and downstream validators.


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
    """Build a User row with signature_full_path stubbed. The fixture-level
    storage path is a plain string (no file written) — tests that need real
    PNG bytes on disk override signature_full_path themselves (see
    sample_user_with_signature in test_glp_signoff_lifecycle)."""
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
    # QAU is an org-level role (grilling decision #5). The CHECK constraint
    # on organization_members.roles only allows the canonical set, so until
    # Task 1 lands the QAU role expansion we use ADMIN here — that grants
    # the QAU user the same permissions surface QAU will eventually have.
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=glp_org.id,
            roles=["MEMBER", "ADMIN"],
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
    """Two-swimlane + three unit-op graph with glpSettings snapshot.

    Lane node ids follow the ``lane-{role_id}`` convention used by
    services/runs/validation.py and services/protocols/lane_layout.py.
    """
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
    """Protocol with glpSettings.glp_enabled=True, Study Director + QAU set,
    two ProtocolRole lanes, three unit-op nodes."""
    import uuid

    sd_role_id = uuid.uuid4()
    op_role_id = uuid.uuid4()

    proto = Protocol(
        name="GLP Test Protocol",
        project_id=test_project.id,
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
async def fresh_equipment(db_session, glp_org) -> Equipment:
    """Equipment whose next_calibration_date is comfortably in the future."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
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
async def imminent_equipment(db_session, glp_org) -> Equipment:
    """Equipment whose calibration expires within the IMMINENT window
    (next_calibration_date = today + 7 days)."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
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
async def expired_equipment(db_session, glp_org) -> Equipment:
    """Equipment whose calibration has lapsed (next_calibration_date 30 days
    in the past)."""
    from datetime import date, timedelta

    eq = Equipment(
        organization_id=glp_org.id,
        name="Expired Bioreactor",
        equipment_type="bioreactor",
        serial_number="BR-EXP-001",
        last_calibration_date=date.today() - timedelta(days=395),
        next_calibration_date=date.today() - timedelta(days=30),
    )
    db_session.add(eq)
    await db_session.flush()
    return eq

"""Tests for the unit op library registry (F-0075)."""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.science import library_registry as lr


@pytest_asyncio.fixture(autouse=True)
async def _reset_registry():
    """Each test starts with the bundled core source loaded.
    Tests that need a clean slate can call lr._reset_for_tests() at the top."""
    lr._reset_for_tests()
    lr.register_source(
        lr.BundledJSONSource(
            Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
        )
    )
    await lr.reload_libraries()
    yield
    # No teardown reset: leaving the registry seeded with bundled core
    # avoids wiping state that subsequent test files (e.g. scoping tests)
    # rely on. Setup re-seeds cleanly anyway.


@pytest.mark.asyncio
async def test_synthetic_uuid_is_deterministic():
    a = lr.synthetic_uuid("core", "mixing")
    b = lr.synthetic_uuid("core", "mixing")
    assert a == b
    assert isinstance(a, uuid.UUID)


@pytest.mark.asyncio
async def test_synthetic_uuid_differs_per_op():
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid(
        "core", "centrifugation"
    )
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid("other", "mixing")


@pytest.mark.asyncio
async def test_bundled_source_loads_core_library():
    src = lr.BundledJSONSource(
        Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
    )
    libs = await src.load()
    assert len(libs) == 1
    core = libs[0]
    assert core.slug == "core"
    assert core.is_default is True
    assert core.version == "1.0.0"
    assert len(core.unit_ops) == 12
    slugs = {op.slug for op in core.unit_ops}
    assert "solution_preparation" in slugs
    assert "mixing" in slugs
    assert "storage" in slugs


@pytest.mark.asyncio
async def test_register_and_reload_populates_cache():
    lr._reset_for_tests()
    fake = _FakeSource(
        [
            lr.Library(
                slug="alpha",
                name="Alpha",
                domain="general",
                description="",
                is_default=True,
                version="1.0.0",
                unit_ops=[
                    lr.UnitOp(
                        slug="op_one",
                        name="Op One",
                        category="Cat",
                        description="",
                        param_schema={},
                        result_schema={},
                    ),
                ],
            ),
        ]
    )
    lr.register_source(fake)
    await lr.reload_libraries()

    assert [lib.slug for lib in lr.list_libraries()] == ["alpha"]
    assert lr.get_library("alpha") is not None
    assert lr.get_op("alpha", "op_one") is not None
    assert lr.get_op("alpha", "missing") is None
    assert lr.default_library_slugs() == ["alpha"]


@pytest.mark.asyncio
async def test_reload_is_atomic_on_source_failure():
    lr._reset_for_tests()
    fake_ok = _FakeSource(
        [
            lr.Library(
                slug="good",
                name="Good",
                domain="general",
                description="",
                is_default=False,
                version="1",
                unit_ops=[],
            ),
        ]
    )
    lr.register_source(fake_ok)
    await lr.reload_libraries()
    assert lr.get_library("good") is not None

    # Replace with a failing source. Reload must raise but leave cache intact.
    lr._reset_sources_for_tests()
    lr.register_source(_FailingSource())
    with pytest.raises(RuntimeError):
        await lr.reload_libraries()
    assert lr.get_library("good") is not None  # cache unchanged


@pytest.mark.asyncio
async def test_last_source_wins_on_slug_collision():
    lr._reset_for_tests()
    earlier = _FakeSource(
        [
            lr.Library(
                slug="x",
                name="Earlier",
                domain="general",
                description="",
                is_default=False,
                version="1",
                unit_ops=[],
            ),
        ]
    )
    later = _FakeSource(
        [
            lr.Library(
                slug="x",
                name="Later",
                domain="general",
                description="",
                is_default=False,
                version="2",
                unit_ops=[],
            ),
        ]
    )
    lr.register_source(earlier)
    lr.register_source(later)
    await lr.reload_libraries()
    assert lr.get_library("x").name == "Later"


@pytest.mark.asyncio
async def test_subscribe_default_libraries_idempotent(
    db_session,
    test_org,
):
    """subscribe_default_libraries can be called repeatedly without error."""
    from sqlalchemy import func, select

    from app.models.science import UnitOpLibrarySubscription

    # test_org fixture already subscribed once. Calling again does nothing.
    await lr.subscribe_default_libraries(db_session, test_org.id)
    await lr.subscribe_default_libraries(db_session, test_org.id)

    count = await db_session.execute(
        select(func.count())
        .select_from(UnitOpLibrarySubscription)
        .where(
            UnitOpLibrarySubscription.organization_id == test_org.id,
        )
    )
    assert count.scalar() == 1  # still just core


# --- Helpers ---


class _FakeSource:
    def __init__(self, libs: list):
        self._libs = libs

    async def load(self):
        return self._libs


class _FailingSource:
    async def load(self):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_register_endpoint_subscribes_new_org_to_core(
    client,
    db_session,
):
    """A user signing up gets a new org auto-subscribed to 'core'."""
    from sqlalchemy import select

    from app.models.iam import Organization
    from app.models.science import UnitOpLibrarySubscription

    resp = await client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "testpass123",
            "full_name": "New User",
        },
    )
    assert resp.status_code in (200, 201), resp.text

    # Find the org that was just created
    org_q = await db_session.execute(
        select(Organization).where(Organization.name.like("%New User%"))
    )
    org = org_q.scalar_one()

    sub_q = await db_session.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org.id,
        )
    )
    assert "core" in {row[0] for row in sub_q.all()}  # register endpoint check


@pytest.mark.asyncio
async def test_create_org_endpoint_subscribes_to_core(
    client,
    auth_headers,
    db_session,
):
    """POST /iam/organizations subscribes the new org to defaults."""
    from sqlalchemy import select

    from app.models.iam import Organization
    from app.models.science import UnitOpLibrarySubscription

    resp = await client.post(
        "/iam/organizations",
        json={"name": "Second Workspace"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_org_id = resp.json()["id"]

    sub_q = await db_session.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == new_org_id,
        )
    )
    assert "core" in {row[0] for row in sub_q.all()}


@pytest.mark.asyncio
async def test_admin_reload_endpoint_as_org_admin(
    client,
    auth_headers,
):
    resp = await client.post(
        "/admin/libraries/reload",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "libraries" in body
    slugs = {entry["slug"] for entry in body["libraries"]}
    assert "core" in slugs
    core = next(e for e in body["libraries"] if e["slug"] == "core")
    assert core["op_count"] == 12
    assert core["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_admin_reload_endpoint_as_member_forbidden(
    client,
    db_session,
    test_org,
):
    from app.core.security import create_access_token, hash_password
    from app.models.iam import OrganizationMember, User

    member = User(
        email="member-reload@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Member",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=member.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()
    token = create_access_token(
        member.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/admin/libraries/reload", headers=headers)
    assert resp.status_code == 403

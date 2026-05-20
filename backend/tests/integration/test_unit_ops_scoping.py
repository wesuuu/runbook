"""Tests for multi-scope unit operations (F-0039).

Covers: global/org/project scoping, permission checks, and union queries.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.projects import Project
from app.models.protocols import UnitOpDefinition

# --- Fixtures ---


@pytest.fixture
def global_op_payload():
    return {
        "name": "Global Buffer Mix",
        "category": "Media Prep",
        "param_schema": {"properties": {"volume_ml": {"type": "number"}}},
    }


@pytest.fixture
def org_op_payload():
    return {
        "name": "Org Custom Wash",
        "category": "Purification",
        "description": "Organization-specific wash step",
        "param_schema": {},
    }


@pytest.fixture
def project_op_payload(test_project: Project):
    return {
        "name": "Project Experimental Step",
        "category": "Reaction",
        "project_id": str(test_project.id),
        "param_schema": {},
    }


@pytest_asyncio.fixture
async def org_unit_op(
    db_session: AsyncSession,
    test_org: Organization,
) -> UnitOpDefinition:
    """An org-scoped unit op."""
    op = UnitOpDefinition(
        name="Org Wash Step",
        category="Purification",
        param_schema={},
        organization_id=test_org.id,
        project_id=None,
    )
    db_session.add(op)
    await db_session.flush()
    return op


@pytest_asyncio.fixture
async def project_unit_op(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
) -> UnitOpDefinition:
    """A project-scoped unit op."""
    op = UnitOpDefinition(
        name="Project Test Step",
        category="Reaction",
        param_schema={},
        organization_id=test_org.id,
        project_id=test_project.id,
    )
    db_session.add(op)
    await db_session.flush()
    return op


@pytest_asyncio.fixture
async def other_org_unit_op(
    db_session: AsyncSession,
    second_org: Organization,
) -> UnitOpDefinition:
    """An org-scoped unit op belonging to a different org."""
    op = UnitOpDefinition(
        name="Other Org Step",
        category="General",
        param_schema={},
        organization_id=second_org.id,
        project_id=None,
    )
    db_session.add(op)
    await db_session.flush()
    return op


# --- GET /unit-ops (scoped listing) ---


@pytest.mark.asyncio
async def test_list_returns_org_ops(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
):
    """Org-scoped ops for the user's org should be returned."""
    resp = await client.get("/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Org Wash Step" in names


@pytest.mark.asyncio
async def test_list_excludes_other_org_ops(
    client: AsyncClient,
    auth_headers: dict,
    other_org_unit_op: UnitOpDefinition,
):
    """Ops from other orgs should NOT be returned."""
    resp = await client.get("/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Other Org Step" not in names


@pytest.mark.asyncio
async def test_list_returns_project_ops_with_param(
    client: AsyncClient,
    auth_headers: dict,
    project_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """Project-scoped ops should be returned when project_id is specified."""
    resp = await client.get(
        f"/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Project Test Step" in names


@pytest.mark.asyncio
async def test_list_excludes_project_ops_without_param(
    client: AsyncClient,
    auth_headers: dict,
    project_unit_op: UnitOpDefinition,
):
    """Project-scoped ops should NOT be returned without project_id param."""
    resp = await client.get("/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Project Test Step" not in names


@pytest.mark.asyncio
async def test_list_union_returns_all_scopes(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    other_org_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """With project_id param, returns library ops + org + project, not other orgs."""
    resp = await client.get(
        f"/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Mixing" in names  # library op (replaces "Seeding")
    assert "Org Wash Step" in names
    assert "Project Test Step" in names
    assert "Other Org Step" not in names


# --- Response schema ---


@pytest.mark.asyncio
async def test_response_includes_scope_field(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """Response should include computed scope field."""
    resp = await client.get(
        f"/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    ops = {op["name"]: op for op in resp.json()}
    assert ops["Mixing"]["scope"] == "global"
    assert ops["Org Wash Step"]["scope"] == "organization"
    assert ops["Project Test Step"]["scope"] == "project"


# --- POST /unit-ops (create with scoping) ---


@pytest.mark.asyncio
async def test_create_org_scoped_op_as_admin(
    client: AsyncClient,
    auth_headers: dict,
):
    """Org admin can create org-scoped ops (no project_id)."""
    resp = await client.post(
        "/unit-ops",
        json={"name": "New Org Op", "category": "General"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Org Op"
    assert data["scope"] == "organization"
    assert data["organization_id"] is not None
    assert data["project_id"] is None


@pytest.mark.asyncio
async def test_create_org_scoped_op_as_member_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    test_org: Organization,
):
    """Non-admin org members cannot create org-scoped ops."""
    from app.core.security import create_access_token, hash_password

    member = User(
        email="member@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Regular Member",
        selected_org_id=test_org.id,
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
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/unit-ops",
        json={"name": "Blocked Op", "category": "General"},
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_project_scoped_op(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    """User with project EDIT permission can create project-scoped ops."""
    resp = await client.post(
        "/unit-ops",
        json={
            "name": "Project Step",
            "category": "Reaction",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["scope"] == "project"
    assert data["project_id"] == str(test_project.id)
    assert data["organization_id"] is not None


@pytest.mark.asyncio
async def test_create_global_op_forbidden(
    client: AsyncClient,
    auth_headers: dict,
):
    """Cannot create global ops via API — there's no way to do so since
    org_id is always set from user.selected_org_id."""
    # Any create without project_id creates org-scoped, not global.
    # This test just confirms the response is org-scoped, not global.
    resp = await client.post(
        "/unit-ops",
        json={"name": "Would-Be Global", "category": "General"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["scope"] == "organization"


# --- PUT /unit-ops/{id} (edit with permissions) ---


@pytest.mark.asyncio
async def test_update_org_op_as_admin(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
):
    """Org admin can edit org-scoped ops."""
    resp = await client.put(
        f"/unit-ops/{org_unit_op.id}",
        json={"name": "Renamed Wash Step"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Wash Step"


@pytest.mark.asyncio
async def test_update_other_org_op_forbidden(
    client: AsyncClient,
    auth_headers: dict,
    other_org_unit_op: UnitOpDefinition,
):
    """Cannot edit ops belonging to another org."""
    resp = await client.put(
        f"/unit-ops/{other_org_unit_op.id}",
        json={"name": "Hacked"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_project_op_with_permission(
    client: AsyncClient,
    auth_headers: dict,
    project_unit_op: UnitOpDefinition,
):
    """User with project EDIT permission can edit project-scoped ops."""
    resp = await client.put(
        f"/unit-ops/{project_unit_op.id}",
        json={"description": "Updated description"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


# --- F-0075 union-assembly tests ---


@pytest.mark.asyncio
async def test_list_returns_subscribed_library_ops(
    client: AsyncClient,
    auth_headers: dict,
):
    """An org subscribed to 'core' sees all 12 core ops."""
    resp = await client.get("/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    ops = resp.json()
    names = {op["name"] for op in ops}
    assert "Solution Preparation" in names
    assert "Mixing" in names
    assert "Storage" in names
    # All core ops carry library_slug
    core_ops = [op for op in ops if op.get("library_slug") == "core"]
    assert len(core_ops) == 12


@pytest.mark.asyncio
async def test_list_excludes_unsubscribed_library_ops(
    client: AsyncClient,
    db_session,
    second_org,
):
    """An org NOT subscribed to a library doesn't see its ops.
    second_org's subscription is provided by the fixture; remove it."""
    from sqlalchemy import delete

    from app.core.security import create_access_token
    from app.models.protocols import UnitOpLibrarySubscription

    await db_session.execute(
        delete(UnitOpLibrarySubscription).where(
            UnitOpLibrarySubscription.organization_id == second_org.id,
        )
    )
    await db_session.flush()

    # Create a user attached to second_org with no library subscription
    from app.core.security import hash_password
    from app.models.iam import OrganizationMember, User

    user = User(
        email="lonely@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Lonely User",
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

    token = create_access_token(
        user.id,
        org_id=second_org.id,
        subscription_tier=second_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/unit-ops", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []  # no library, no custom ops


# --- F-0075 copy-on-write tests ---


@pytest.mark.asyncio
async def test_put_on_library_op_creates_override(
    client: AsyncClient,
    auth_headers,
    db_session,
    test_org,
):
    """PUT on a JSON op id inserts an override row in this org."""
    from app.models.protocols import UnitOpDefinition
    from app.services.protocols import library_registry

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    resp = await client.put(
        f"/unit-ops/{synth_id}",
        json={"name": "Custom Mixing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Custom Mixing"
    assert body["library_slug"] == "core"
    assert body["organization_id"] == str(test_org.id)
    assert body["id"] == str(synth_id)

    # DB has the override row with the same id as the synthetic UUID
    row = await db_session.get(UnitOpDefinition, synth_id)
    assert row is not None
    assert row.source_library_slug == "core"
    assert row.source_op_slug == "mixing"
    assert row.organization_id == test_org.id


@pytest.mark.asyncio
async def test_second_put_updates_existing_override(
    client: AsyncClient,
    auth_headers,
    db_session,
):
    from sqlalchemy import func, select

    from app.models.protocols import UnitOpDefinition
    from app.services.protocols import library_registry

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    await client.put(
        f"/unit-ops/{synth_id}",
        json={"name": "First Rename"},
        headers=auth_headers,
    )
    await client.put(
        f"/unit-ops/{synth_id}",
        json={"name": "Second Rename"},
        headers=auth_headers,
    )

    count_q = await db_session.execute(
        select(func.count())
        .select_from(UnitOpDefinition)
        .where(
            UnitOpDefinition.id == synth_id,
        )
    )
    assert count_q.scalar() == 1

    row = await db_session.get(UnitOpDefinition, synth_id)
    assert row.name == "Second Rename"


@pytest.mark.asyncio
async def test_override_isolated_per_org(
    client: AsyncClient,
    auth_headers,
    second_auth_headers,
):
    """An override in org A doesn't leak into org B's listing."""
    from app.services.protocols import library_registry

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    await client.put(
        f"/unit-ops/{synth_id}",
        json={"name": "Org-A Mixing"},
        headers=auth_headers,
    )

    resp_b = await client.get("/unit-ops", headers=second_auth_headers)
    assert resp_b.status_code == 200
    by_id = {op["id"]: op for op in resp_b.json()}
    # Org B still sees the original Mixing, not "Org-A Mixing"
    assert by_id[str(synth_id)]["name"] == "Mixing"


@pytest.mark.asyncio
async def test_put_on_unknown_uuid_returns_404(
    client: AsyncClient,
    auth_headers,
):
    import uuid as _uuid

    bogus = _uuid.uuid4()
    resp = await client.put(
        f"/unit-ops/{bogus}",
        json={"name": "Whatever"},
        headers=auth_headers,
    )
    assert resp.status_code == 404

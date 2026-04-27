"""Tests for multi-scope unit operations (F-0039).

Covers: global/org/project scoping, permission checks, and union queries.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    Organization,
    OrganizationMember,
    User,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project, UnitOpDefinition


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
async def global_unit_op(db_session: AsyncSession) -> UnitOpDefinition:
    """A global unit op (like seed data)."""
    op = UnitOpDefinition(
        name="Seeding",
        category="Cell Culture",
        param_schema={},
        organization_id=None,
        project_id=None,
    )
    db_session.add(op)
    await db_session.flush()
    return op


@pytest_asyncio.fixture
async def org_unit_op(
    db_session: AsyncSession, test_org: Organization,
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
    db_session: AsyncSession, test_org: Organization, test_project: Project,
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
    db_session: AsyncSession, second_org: Organization,
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


# --- GET /science/unit-ops (scoped listing) ---


@pytest.mark.asyncio
async def test_list_returns_global_ops(
    client: AsyncClient,
    auth_headers: dict,
    global_unit_op: UnitOpDefinition,
):
    """Global ops should always be returned."""
    resp = await client.get("/science/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Seeding" in names


@pytest.mark.asyncio
async def test_list_returns_org_ops(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
):
    """Org-scoped ops for the user's org should be returned."""
    resp = await client.get("/science/unit-ops", headers=auth_headers)
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
    resp = await client.get("/science/unit-ops", headers=auth_headers)
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
        f"/science/unit-ops?project_id={test_project.id}",
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
    resp = await client.get("/science/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Project Test Step" not in names


@pytest.mark.asyncio
async def test_list_union_returns_all_scopes(
    client: AsyncClient,
    auth_headers: dict,
    global_unit_op: UnitOpDefinition,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    other_org_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """With project_id param, should return global + org + project, not other orgs."""
    resp = await client.get(
        f"/science/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Seeding" in names  # global
    assert "Org Wash Step" in names  # org
    assert "Project Test Step" in names  # project
    assert "Other Org Step" not in names  # other org


# --- Response schema ---


@pytest.mark.asyncio
async def test_response_includes_scope_field(
    client: AsyncClient,
    auth_headers: dict,
    global_unit_op: UnitOpDefinition,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """Response should include computed scope field."""
    resp = await client.get(
        f"/science/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    ops = {op["name"]: op for op in resp.json()}
    assert ops["Seeding"]["scope"] == "global"
    assert ops["Org Wash Step"]["scope"] == "organization"
    assert ops["Project Test Step"]["scope"] == "project"


# --- POST /science/unit-ops (create with scoping) ---


@pytest.mark.asyncio
async def test_create_org_scoped_op_as_admin(
    client: AsyncClient,
    auth_headers: dict,
):
    """Org admin can create org-scoped ops (no project_id)."""
    resp = await client.post(
        "/science/unit-ops",
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
    from app.core.security import hash_password, create_access_token

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
            role="MEMBER",
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
        "/science/unit-ops",
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
        "/science/unit-ops",
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
        "/science/unit-ops",
        json={"name": "Would-Be Global", "category": "General"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["scope"] == "organization"


# --- PUT /science/unit-ops/{id} (edit with permissions) ---


@pytest.mark.asyncio
async def test_update_global_op_forbidden(
    client: AsyncClient,
    auth_headers: dict,
    global_unit_op: UnitOpDefinition,
):
    """Global ops are read-only via API."""
    resp = await client.put(
        f"/science/unit-ops/{global_unit_op.id}",
        json={"name": "Renamed"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_org_op_as_admin(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
):
    """Org admin can edit org-scoped ops."""
    resp = await client.put(
        f"/science/unit-ops/{org_unit_op.id}",
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
        f"/science/unit-ops/{other_org_unit_op.id}",
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
        f"/science/unit-ops/{project_unit_op.id}",
        json={"description": "Updated description"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


# --- F-0075 union-assembly tests ---


@pytest.mark.asyncio
async def test_list_returns_subscribed_library_ops(
    client: AsyncClient, auth_headers: dict,
):
    """An org subscribed to 'core' sees all 12 core ops."""
    resp = await client.get("/science/unit-ops", headers=auth_headers)
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
    client: AsyncClient, db_session, second_org,
):
    """An org NOT subscribed to a library doesn't see its ops.
    second_org's subscription is provided by the fixture; remove it."""
    from app.models.science import UnitOpLibrarySubscription
    from sqlalchemy import delete
    from app.core.security import create_access_token

    await db_session.execute(
        delete(UnitOpLibrarySubscription).where(
            UnitOpLibrarySubscription.organization_id == second_org.id,
        )
    )
    await db_session.flush()

    # Create a user attached to second_org with no library subscription
    from app.models.iam import User, OrganizationMember
    from app.core.security import hash_password
    user = User(
        email="lonely@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Lonely User",
        selected_org_id=second_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=second_org.id, role="ADMIN",
    ))
    await db_session.flush()

    token = create_access_token(
        user.id, org_id=second_org.id,
        subscription_tier=second_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/science/unit-ops", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []  # no library, no custom ops

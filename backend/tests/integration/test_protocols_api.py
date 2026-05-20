import pytest
from httpx import AsyncClient
from sqlalchemy import select
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
from app.models.protocols import Protocol


@pytest.mark.asyncio
async def test_delete_sample_protocol_hard_deletes(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_project: Project,
    test_org: Organization,
):
    """Sample/tour protocols should always be hard-deleted,
    regardless of status (APPROVED, etc)."""
    proto = Protocol(
        name="Sample Protocol",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        is_tour_sample=True,
    )
    db_session.add(proto)
    await db_session.flush()
    protocol_id = proto.id

    resp = await client.delete(
        f"/protocols/{protocol_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "deleted"

    result = await db_session.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/protocols",
        json={
            "name": "New Protocol",
            "project_id": str(test_project.id),
            "graph": {},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Protocol"


@pytest.mark.asyncio
async def test_create_protocol_no_project_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    resp = await client.post(
        "/protocols",
        json={
            "name": "Should Fail",
            "project_id": str(test_project.id),
            "graph": {},
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_protocol_with_project_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Readable Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/protocols/{protocol.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Readable Protocol"


@pytest.mark.asyncio
async def test_get_protocol_without_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    second_user: User,
):
    protocol = Protocol(
        name="Secret Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/protocols/{protocol.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_protocol_with_edit_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Editable Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}",
        json={"name": "Updated Protocol"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Protocol"


@pytest.mark.asyncio
async def test_update_protocol_view_only_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    # Give second_user VIEW only on the project
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=second_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.VIEW.value,
        )
    )
    await db_session.flush()

    protocol = Protocol(
        name="View Only Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}",
        json={"name": "Should Fail"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_protocols_for_project(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Listed Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_protocols_filters_archived_by_default(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Archived protocols are hidden by default and shown with include_archived=true."""
    active = Protocol(
        name="Active Protocol",
        project_id=test_project.id,
        graph={},
        status="DRAFT",
    )
    archived = Protocol(
        name="Archived Protocol",
        project_id=test_project.id,
        graph={},
        status="ARCHIVED",
    )
    db_session.add_all([active, archived])
    await db_session.flush()

    # Default: archived hidden
    resp = await client.get(
        f"/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Active Protocol" in names
    assert "Archived Protocol" not in names

    # include_archived=true: archived included
    resp = await client.get(
        f"/projects/{test_project.id}/protocols",
        params={"include_archived": "true"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Active Protocol" in names
    assert "Archived Protocol" in names


@pytest.mark.asyncio
async def test_list_protocols_surfaces_latest_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Approved protocols with an unpublished draft should expose
    latest_draft_version_number so the project table can badge them."""
    from app.models.protocols import ProtocolVersion

    with_draft = Protocol(
        name="Has Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=4,
    )
    no_draft = Protocol(
        name="No Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=2,
    )
    db_session.add_all([with_draft, no_draft])
    await db_session.flush()
    db_session.add(
        ProtocolVersion(
            protocol_id=with_draft.id,
            version_number=5,
            name=with_draft.name,
            graph={},
            is_draft=True,
        )
    )
    # Older non-draft version shouldn't trigger the badge.
    db_session.add(
        ProtocolVersion(
            protocol_id=no_draft.id,
            version_number=1,
            name=no_draft.name,
            graph={},
            is_draft=False,
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    by_name = {p["name"]: p for p in resp.json()}
    assert by_name["Has Draft"]["latest_draft_version_number"] == 5
    assert by_name["No Draft"]["latest_draft_version_number"] is None


@pytest.mark.asyncio
async def test_get_protocol_surfaces_latest_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """The single-protocol GET endpoint must surface
    latest_draft_version_number so the editor's version toggle can jump
    to an unpublished draft."""
    from app.models.protocols import ProtocolVersion

    protocol = Protocol(
        name="Toggle Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=4,
    )
    db_session.add(protocol)
    await db_session.flush()
    db_session.add(
        ProtocolVersion(
            protocol_id=protocol.id,
            version_number=5,
            name=protocol.name,
            graph={},
            is_draft=True,
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/protocols/{protocol.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["latest_draft_version_number"] == 5

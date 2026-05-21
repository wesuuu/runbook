import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import Project
from app.models.protocols import Protocol


@pytest.mark.asyncio
async def test_publish_protocol_success(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that publishing a draft version updates the main protocol."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save as draft (creates draft version v1)
    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "test"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Publish the draft
    resp = await client.post(
        f"/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["version_number"] == 1
    assert len(result["graph"]["nodes"]) == 1


@pytest.mark.asyncio
async def test_save_as_draft_creates_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """save_as_draft creates a draft snapshot without bumping version_number.

    For DRAFT-status protocols the live graph is also synced to the new draft
    so role/lane mutations stay consistent — see
    `test_save_as_draft_syncs_live_graph_for_unpublished_protocol`.
    """
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()
    original_version = protocol.version_number

    # Save as draft
    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "draft"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Check that main protocol version_number didn't change
    result = resp.json()
    assert result["version_number"] == original_version

    # Check versions list includes the draft
    resp = await client.get(
        f"/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    draft_found = any(v.get("version_number") == 1 for v in versions)
    assert draft_found


@pytest.mark.asyncio
async def test_publish_draft_not_found(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test publishing non-existent draft version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.post(
        f"/protocols/{protocol.id}/publish-draft?version_number=999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_save_draft_always_creates_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Save-as-draft always creates a draft version, even for unchanged graphs.

    The user's explicit intent to save means a draft must exist so it can be
    published. Skipping draft creation caused publish to fail with 404.
    """
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [{"id": "1"}], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save the exact same graph
    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # A draft v1 should now exist so publish can find it
    resp = await client.get(
        f"/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    versions = resp.json()
    assert any(v["version_number"] == 1 for v in versions)


@pytest.mark.asyncio
async def test_save_as_draft_syncs_live_graph_for_unpublished_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Unpublished (DRAFT) protocol's live graph mirrors the saved draft.

    Otherwise role mutations (which write to protocols.graph directly) and
    editor edits (which only wrote to a snapshot) drift apart and orphan
    swimLane nodes survive after their roles are deleted.
    """
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [{"id": "stale"}], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    new_graph = {"nodes": [{"id": "fresh"}], "edges": []}
    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(protocol)
    assert protocol.graph == new_graph


@pytest.mark.asyncio
async def test_save_as_draft_preserves_live_graph_for_published_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """APPROVED protocol's live graph stays frozen until the draft is published."""
    published_graph = {"nodes": [{"id": "published"}], "edges": []}
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="APPROVED",
        version_number=1,
        graph=published_graph,
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "wip"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(protocol)
    assert protocol.graph == published_graph


@pytest.mark.asyncio
async def test_list_versions_returns_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """List endpoint exposes the version description field."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    from app.models.protocols import ProtocolVersion

    version = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=1,
        name=protocol.name,
        graph={"nodes": [], "edges": []},
        description="Tightened DO range",
        change_summary="DO 30 -> 25",
        is_draft=False,
    )
    db_session.add(version)
    await db_session.flush()

    resp = await client.get(
        f"/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["description"] == "Tightened DO range"
    assert versions[0]["change_summary"] == "DO 30 -> 25"


@pytest.mark.asyncio
async def test_publish_draft_persists_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft accepts an optional body with description; the value is
    written onto the published version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"description": "Switched buffer from PBS to TBS"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Switched buffer from PBS to TBS"


@pytest.mark.asyncio
async def test_publish_draft_persists_change_summary(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft writes change_summary from the body."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"change_summary": "DO range tightened"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.json()["change_summary"] == "DO range tightened"


@pytest.mark.asyncio
async def test_publish_draft_without_body_still_works(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Existing callers that don't send a body must continue to work.
    Backward-compatibility regression guard."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
        slug=f"test-protocol-{uuid.uuid4().hex[:8]}",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["version_number"] == 1

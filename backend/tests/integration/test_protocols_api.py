import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization
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
        f"/science/protocols/{protocol_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "deleted"

    result = await db_session.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    assert result.scalar_one_or_none() is None

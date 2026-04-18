"""Unit tests for app.services.onboarding."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.science import Project, Protocol, Run
from app.services.onboarding import (
    delete_sample_run,
    find_or_create_sample_project,
    find_or_create_sample_protocol,
    find_or_create_sample_run,
    get_sample_protocol_graph,
)


@pytest_asyncio.fixture
async def org_and_user(db_session: AsyncSession):
    org = Organization(name="Acme")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="sample@example.com",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    return org, user


@pytest.mark.asyncio
async def test_get_sample_protocol_graph_returns_prepopulated_nodes():
    graph = get_sample_protocol_graph()
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) >= 3
    assert len(graph["edges"]) >= 2


@pytest.mark.asyncio
async def test_find_or_create_sample_project_creates_when_none(db_session, org_and_user):
    org, user = org_and_user
    project = await find_or_create_sample_project(db_session, user, org)
    assert project.id is not None
    assert project.organization_id == org.id


@pytest.mark.asyncio
async def test_find_or_create_sample_project_reuses_existing_active(db_session, org_and_user):
    org, user = org_and_user
    existing = Project(name="Existing", organization_id=org.id)
    db_session.add(existing)
    await db_session.commit()

    project = await find_or_create_sample_project(db_session, user, org)
    assert project.id == existing.id


@pytest.mark.asyncio
async def test_find_or_create_sample_protocol_marks_flag(db_session, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db_session, user, org)
    assert protocol.is_tour_sample is True
    assert protocol.project_id is not None
    assert len(protocol.graph.get("nodes", [])) >= 3


@pytest.mark.asyncio
async def test_find_or_create_sample_protocol_reuses_by_flag(db_session, org_and_user):
    org, user = org_and_user
    first = await find_or_create_sample_protocol(db_session, user, org)
    second = await find_or_create_sample_protocol(db_session, user, org)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_find_or_create_sample_run_cleans_orphans(db_session, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db_session, user, org)
    first = await find_or_create_sample_run(db_session, user, protocol)
    second = await find_or_create_sample_run(db_session, user, protocol)

    assert first.id != second.id
    result = await db_session.get(Run, first.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_sample_run_is_idempotent(db_session, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db_session, user, org)
    run = await find_or_create_sample_run(db_session, user, protocol)

    await delete_sample_run(db_session, user)
    await delete_sample_run(db_session, user)

    result = await db_session.get(Run, run.id)
    assert result is None

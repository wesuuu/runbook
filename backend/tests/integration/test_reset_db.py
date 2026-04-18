"""Integration tests for reset_database against a real DB.

Uses the conftest ``db_session`` fixture (per-test SAVEPOINT); the outer
rollback undoes everything at teardown so tests don't leak state.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.reset import reset_database
from app.db.seed import (
    ORG_ID,
    ORG_ID_2,
    PROJECT_MAB,
    PROJECT_VACCINE,
    TEAM_DOWNSTREAM,
    TEAM_QA,
    TEAM_UPSTREAM,
    USER_ADMIN,
    USER_DOWNSTREAM_LEAD,
    USER_SCIENTIST1,
    USER_SCIENTIST2,
    USER_UPSTREAM_LEAD,
    USER_VIEWER,
)
from app.models.execution import AuditLog
from app.models.iam import Organization, Team, User
from app.models.library import Document
from app.models.science import Project, Protocol, Run, UnitOpDefinition


@pytest.mark.asyncio
async def test_reset_wipes_user_generated_data(
    db_session, test_user, test_org, test_project
):
    # Seed some user-generated junk across several wipe-target tables.
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    run = Run(
        name="Test Run",
        project_id=test_project.id,
        protocol_id=protocol.id,
        status="DRAFT",
        graph={"nodes": [], "edges": []},
    )
    db_session.add(run)

    db_session.add(
        AuditLog(
            entity_type="PROTOCOL",
            entity_id=protocol.id,
            actor_id=test_user.id,
            action="TEST_ACTION",
            changes={},
        )
    )
    await db_session.flush()

    # Precondition: rows exist.
    assert (await db_session.execute(select(Protocol))).scalars().first() is not None
    assert (await db_session.execute(select(Run))).scalars().first() is not None
    assert (await db_session.execute(select(AuditLog))).scalars().first() is not None

    # Act
    await reset_database(db_session)

    # Postcondition: wipe tables empty.
    assert (await db_session.execute(select(Protocol))).scalars().all() == []
    assert (await db_session.execute(select(Run))).scalars().all() == []
    assert (await db_session.execute(select(AuditLog))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


@pytest.mark.asyncio
async def test_reset_populates_seed_baseline(db_session):
    await reset_database(db_session)

    # Users
    user_ids = {
        USER_ADMIN, USER_UPSTREAM_LEAD, USER_DOWNSTREAM_LEAD,
        USER_SCIENTIST1, USER_SCIENTIST2, USER_VIEWER,
    }
    rows = (await db_session.execute(select(User.id))).scalars().all()
    assert user_ids.issubset(set(rows))

    # Orgs
    orgs = (await db_session.execute(select(Organization.id))).scalars().all()
    assert {ORG_ID, ORG_ID_2}.issubset(set(orgs))

    # Teams
    teams = (await db_session.execute(select(Team.id))).scalars().all()
    assert {TEAM_UPSTREAM, TEAM_DOWNSTREAM, TEAM_QA}.issubset(set(teams))

    # Projects
    projects = (await db_session.execute(select(Project.id))).scalars().all()
    assert {PROJECT_MAB, PROJECT_VACCINE}.issubset(set(projects))

    # Unit ops (at least one)
    ops = (await db_session.execute(select(UnitOpDefinition))).scalars().all()
    assert len(ops) >= 1


@pytest.mark.asyncio
async def test_reset_is_idempotent(db_session):
    await reset_database(db_session)
    # Second call must not raise and must leave state stable.
    await reset_database(db_session)

    users = (await db_session.execute(select(User.id))).scalars().all()
    orgs = (await db_session.execute(select(Organization.id))).scalars().all()
    # Exactly the seed counts — running twice didn't duplicate rows.
    assert len([u for u in users if u in {
        USER_ADMIN, USER_UPSTREAM_LEAD, USER_DOWNSTREAM_LEAD,
        USER_SCIENTIST1, USER_SCIENTIST2, USER_VIEWER,
    }]) == 6
    assert len([o for o in orgs if o in {ORG_ID, ORG_ID_2}]) == 2


@pytest.mark.asyncio
async def test_reset_preserves_baseline_ids(db_session):
    await reset_database(db_session)
    before_users = set((await db_session.execute(select(User.id))).scalars().all())
    before_orgs = set((await db_session.execute(select(Organization.id))).scalars().all())
    before_projects = set(
        (await db_session.execute(select(Project.id))).scalars().all()
    )

    # Add a stray Protocol to trigger a wipe cycle.
    proj_id = next(iter(before_projects))
    db_session.add(Protocol(
        name="ephemeral",
        project_id=proj_id,
        graph={"nodes": [], "edges": []},
    ))
    await db_session.flush()

    await reset_database(db_session)

    after_users = set((await db_session.execute(select(User.id))).scalars().all())
    after_orgs = set((await db_session.execute(select(Organization.id))).scalars().all())
    after_projects = set(
        (await db_session.execute(select(Project.id))).scalars().all()
    )

    # Baseline UUIDs unchanged — no churn on preserve tables.
    assert before_users == after_users
    assert before_orgs == after_orgs
    assert before_projects == after_projects

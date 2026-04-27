"""Integration tests for reset_database against a real DB.

Uses the conftest ``db_session`` fixture (per-test SAVEPOINT); the outer
rollback undoes everything at teardown so tests don't leak state.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.reset import reset_database
from app.db.seed import (ORG_ID, ORG_ID_2, PROJECT_MAB, PROJECT_VACCINE,
                         TEAM_DOWNSTREAM, TEAM_QA, TEAM_UPSTREAM, USER_ADMIN,
                         USER_DOWNSTREAM_LEAD, USER_SCIENTIST1,
                         USER_SCIENTIST2, USER_UPSTREAM_LEAD, USER_VIEWER)
from app.models.execution import AuditLog
from app.models.iam import Organization, Team, User
from app.models.library import Document
from app.models.science import (Project, Protocol, Run,
                                UnitOpLibrarySubscription)


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
        USER_ADMIN,
        USER_UPSTREAM_LEAD,
        USER_DOWNSTREAM_LEAD,
        USER_SCIENTIST1,
        USER_SCIENTIST2,
        USER_VIEWER,
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

    # Library subscriptions (at least one per seeded org)
    subs = (await db_session.execute(select(UnitOpLibrarySubscription))).scalars().all()
    assert len(subs) >= 1


@pytest.mark.asyncio
async def test_reset_is_idempotent(db_session):
    await reset_database(db_session)
    # Second call must not raise and must leave state stable.
    await reset_database(db_session)

    users = (await db_session.execute(select(User.id))).scalars().all()
    orgs = (await db_session.execute(select(Organization.id))).scalars().all()
    # Exactly the seed counts — running twice didn't duplicate rows.
    assert (
        len(
            [
                u
                for u in users
                if u
                in {
                    USER_ADMIN,
                    USER_UPSTREAM_LEAD,
                    USER_DOWNSTREAM_LEAD,
                    USER_SCIENTIST1,
                    USER_SCIENTIST2,
                    USER_VIEWER,
                }
            ]
        )
        == 6
    )
    assert len([o for o in orgs if o in {ORG_ID, ORG_ID_2}]) == 2


@pytest.mark.asyncio
async def test_reset_preserves_baseline_rows(db_session):
    """Reset must leave preserve-table rows untouched, not wipe-and-reinsert.

    The seed UUIDs are fixed literals, so an ID-only check is tautological:
    it passes whether rows were preserved OR deleted-and-recreated. Snapshot
    ``created_at`` too — if the row was wiped and re-inserted, the server
    default fires again and the timestamp changes.
    """
    # First reset populates the baseline.
    await reset_database(db_session)
    before_users = {
        u.id: u.created_at
        for u in (await db_session.execute(select(User))).scalars().all()
    }
    before_orgs = {
        o.id: o.created_at
        for o in (await db_session.execute(select(Organization))).scalars().all()
    }
    before_projects = {
        p.id: p.created_at
        for p in (await db_session.execute(select(Project))).scalars().all()
    }

    # Add a stray Protocol so the next reset has actual work to do.
    proj_id = next(iter(before_projects))
    db_session.add(
        Protocol(
            name="ephemeral",
            project_id=proj_id,
            graph={"nodes": [], "edges": []},
        )
    )
    await db_session.flush()

    # Second reset: wipes the protocol, re-runs idempotent seed.
    await reset_database(db_session)

    after_users = {
        u.id: u.created_at
        for u in (await db_session.execute(select(User))).scalars().all()
    }
    after_orgs = {
        o.id: o.created_at
        for o in (await db_session.execute(select(Organization))).scalars().all()
    }
    after_projects = {
        p.id: p.created_at
        for p in (await db_session.execute(select(Project))).scalars().all()
    }

    # Equal IDs AND equal created_at means the rows survived — if they had
    # been TRUNCATEd and re-inserted by the idempotent seed, created_at
    # would advance to the second reset's wall clock.
    assert before_users == after_users, (
        "user rows were wiped-and-reinserted (created_at changed); "
        "reset should have preserved them"
    )
    assert (
        before_orgs == after_orgs
    ), "organization rows were wiped-and-reinserted (created_at changed)"
    assert (
        before_projects == after_projects
    ), "project rows were wiped-and-reinserted (created_at changed)"

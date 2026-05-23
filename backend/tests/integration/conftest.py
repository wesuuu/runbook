"""Integration test fixtures for F-0043 experiments."""

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from app.core.security import create_access_token, hash_password
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.runs import Experiment, Run, RunStatus


def _ts(offset_seconds: int = 0) -> str:
    """ISO timestamp offset by `offset_seconds` from now."""
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)
    return dt.isoformat()


@pytest_asyncio.fixture
async def experiment_with_notes(db_session, test_project):
    """Experiment with one observation note + one run with an anomaly note."""
    exp = Experiment(
        name="Experiment With Notes",
        project_id=test_project.id,
        slug="integ-exp-with-notes",
        status="ACTIVE",
        notes=[
            {
                "id": str(uuid.uuid4()),
                "content": "Observed pH drift",
                "author_id": str(uuid.uuid4()),
                "author_name": "Alice",
                "created_at": _ts(200),
                "flags": ["observation"],
            },
            {
                "id": str(uuid.uuid4()),
                "content": "Anomalous temperature spike",
                "author_id": str(uuid.uuid4()),
                "author_name": "Bob",
                "created_at": _ts(100),
                "flags": ["anomaly"],
            },
        ],
    )
    db_session.add(exp)
    await db_session.flush()

    run = Run(
        name="Run A",
        slug="integ-run-a-notes",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.COMPLETED,
        notes=[
            {
                "id": str(uuid.uuid4()),
                "content": "Run anomaly observed",
                "author_id": str(uuid.uuid4()),
                "author_name": "Carol",
                "created_at": _ts(50),
                "flags": ["anomaly"],
                "run_status": RunStatus.COMPLETED.value,
            },
        ],
    )
    db_session.add(run)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_with_open_run(db_session, test_project):
    """Experiment with one COMPLETED + one PLANNED run (exercises OPEN_RUNS branch)."""
    exp = Experiment(
        name="Experiment with Open Run",
        description="Test experiment with open run",
        project_id=test_project.id,
        slug="exp-open-run",
        status="ACTIVE",
        conclusion="Some conclusion text.",
    )
    db_session.add(exp)
    await db_session.flush()

    db_session.add(
        Run(
            name="Completed Run",
            slug="open-run-completed",
            project_id=test_project.id,
            experiment_id=exp.id,
            status=RunStatus.COMPLETED,
        )
    )
    db_session.add(
        Run(
            name="Open Run",
            slug="open-run-planned",
            project_id=test_project.id,
            experiment_id=exp.id,
            status=RunStatus.PLANNED,
        )
    )
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_terminal_no_conclusion(db_session, test_project):
    """Experiment with one COMPLETED run but no conclusion text."""
    exp = Experiment(
        name="Experiment Terminal No Conclusion",
        description="Test experiment with completed run, no conclusion",
        project_id=test_project.id,
        slug="exp-terminal-no-conclusion",
        status="COMPLETED",
    )
    db_session.add(exp)
    await db_session.flush()

    run = Run(
        name="Completed Run",
        slug="completed-run",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_ready_to_lock(db_session, test_project):
    """Experiment with one COMPLETED run and conclusion text, ready to lock."""
    exp = Experiment(
        name="Experiment Ready to Lock",
        description="Test experiment ready to lock",
        project_id=test_project.id,
        slug="exp-ready-lock",
        status="COMPLETED",
        conclusion="Final conclusion text for locking.",
    )
    db_session.add(exp)
    await db_session.flush()

    run = Run(
        name="Completed Run",
        slug="completed-run",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_only_archived_runs(db_session, test_project):
    """Experiment with all runs ARCHIVED and conclusion text."""
    exp = Experiment(
        name="Experiment Only Archived",
        description="Test experiment with only archived runs",
        project_id=test_project.id,
        slug="exp-archived-only",
        status="ARCHIVED",
        conclusion="Conclusion text but no completed runs.",
    )
    db_session.add(exp)
    await db_session.flush()

    run = Run(
        name="Archived Run",
        slug="archived-run",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.ARCHIVED,
    )
    db_session.add(run)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def admin_headers(db_session, test_user, test_org):
    """Headers for a user with ADMIN permission on test_project."""
    # test_user already has ADMIN permission via the test_project fixture
    token = create_access_token(
        test_user.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def viewer_headers(db_session, test_project, test_org):
    """Headers for a user with VIEW (limited) permission on test_project."""
    # Create a separate user with VIEW permission
    viewer = User(
        email="viewer@example.com",
        hashed_password=hash_password("viewerpass"),
        full_name="Viewer User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(viewer)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            user_id=viewer.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=viewer.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.VIEW.value,
        )
    )
    await db_session.flush()

    token = create_access_token(
        viewer.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def seeded_run(db_session, test_project):
    """A single run in test_project with a unique slug for testing."""
    run = Run(
        name="Seeded Test Run",
        slug="seeded-test-run",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
    )
    db_session.add(run)
    await db_session.flush()
    return run

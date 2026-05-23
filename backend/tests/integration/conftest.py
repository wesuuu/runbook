"""Integration test fixtures for F-0043 experiments."""

from datetime import datetime, timezone

import pytest_asyncio

from app.models.runs import Experiment, Run, RunStatus


@pytest_asyncio.fixture
async def experiment_with_open_run(db_session, test_project):
    """Experiment with one PLANNED run."""
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

    run = Run(
        name="Open Run",
        slug="open-run",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.PLANNED,
    )
    db_session.add(run)
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

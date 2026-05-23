"""Fixtures for unit tests of experiment services — F-0043."""

import uuid
from datetime import datetime, timezone

import pytest_asyncio

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
        slug="exp-with-notes",
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
        slug="run-a-notes",
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
async def experiment_with_run_observation_note(db_session, test_project):
    """Run has a note flagged 'observation' (not 'anomaly') — must be excluded.

    Also has a valid anomaly note — that one must appear.
    """
    exp = Experiment(
        name="Experiment Run Obs Note",
        project_id=test_project.id,
        slug="exp-run-obs-note",
        status="ACTIVE",
        notes=[],
    )
    db_session.add(exp)
    await db_session.flush()

    run = Run(
        name="Run B",
        slug="run-b-obs-note",
        project_id=test_project.id,
        experiment_id=exp.id,
        status=RunStatus.ACTIVE,
        notes=[
            {
                "id": str(uuid.uuid4()),
                "content": "This run note is only an observation — must not surface",
                "author_id": str(uuid.uuid4()),
                "author_name": "Dave",
                "created_at": _ts(300),
                "flags": ["observation"],
                "run_status": RunStatus.ACTIVE.value,
            },
            {
                "id": str(uuid.uuid4()),
                "content": "Valid run anomaly",
                "author_id": str(uuid.uuid4()),
                "author_name": "Eve",
                "created_at": _ts(100),
                "flags": ["anomaly"],
                "run_status": RunStatus.ACTIVE.value,
            },
        ],
    )
    db_session.add(run)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_with_malformed_notes(db_session, test_project):
    """Experiment whose notes array contains malformed entries (missing created_at / flags)."""
    exp = Experiment(
        name="Experiment Malformed Notes",
        project_id=test_project.id,
        slug="exp-malformed-notes",
        status="DRAFT",
        notes=[
            # Missing created_at — must be silently dropped
            {
                "id": str(uuid.uuid4()),
                "content": "No timestamp",
                "author_id": str(uuid.uuid4()),
                "author_name": "Ghost",
                "flags": ["observation"],
            },
            # Missing flags / flag — must be silently dropped
            {
                "id": str(uuid.uuid4()),
                "content": "No flags at all",
                "author_id": str(uuid.uuid4()),
                "author_name": "Phantom",
                "created_at": _ts(50),
            },
            # Valid observation note — must survive
            {
                "id": str(uuid.uuid4()),
                "content": "Good observation note",
                "author_id": str(uuid.uuid4()),
                "author_name": "Valid",
                "created_at": _ts(10),
                "flags": ["observation"],
            },
        ],
    )
    db_session.add(exp)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def empty_experiment(db_session, test_project):
    """Experiment with no notes and no runs."""
    exp = Experiment(
        name="Empty Experiment",
        project_id=test_project.id,
        slug="exp-empty",
        status="DRAFT",
        notes=[],
    )
    db_session.add(exp)
    await db_session.flush()
    return exp


@pytest_asyncio.fixture
async def experiment_with_600_notes(db_session, test_project):
    """Experiment with 600 observation notes on the experiment itself."""
    notes = [
        {
            "id": str(uuid.uuid4()),
            "content": f"Observation {i}",
            "author_id": str(uuid.uuid4()),
            "author_name": "Bulk Author",
            "created_at": _ts(600 - i),  # older notes have larger offset
            "flags": ["observation"],
        }
        for i in range(600)
    ]
    exp = Experiment(
        name="Experiment 600 Notes",
        project_id=test_project.id,
        slug="exp-600-notes",
        status="ACTIVE",
        notes=notes,
    )
    db_session.add(exp)
    await db_session.flush()
    return exp

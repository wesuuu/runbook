"""Unit tests for QA-0008 Run production metadata fields."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Run, RunStatus


@pytest.mark.asyncio
async def test_run_has_lot_and_batch_columns(db_session: AsyncSession, test_project):
    r = Run(
        name="R",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        slug="r-lot-batch",
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
        lot_number="LOT-2026-001",
        batch_number="BAT-7",
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.lot_number == "LOT-2026-001"
    assert r.batch_number == "BAT-7"


@pytest.mark.asyncio
async def test_run_lot_and_batch_nullable(db_session: AsyncSession, test_project):
    r = Run(
        name="experiment-style",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        slug="experiment-style",
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.lot_number is None
    assert r.batch_number is None

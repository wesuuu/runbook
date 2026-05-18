"""Unit tests for F-0086 Run produces_lot designation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Run, RunStatus


@pytest.mark.asyncio
async def test_run_produces_lot_defaults_false(db_session: AsyncSession, test_project):
    r = Run(
        name="not-a-lot-producer",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.produces_lot is False


@pytest.mark.asyncio
async def test_run_produces_lot_can_be_set_true(db_session: AsyncSession, test_project):
    r = Run(
        name="lot-producer",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
        produces_lot=True,
        lot_number="LOT-000001",
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.produces_lot is True
    assert r.lot_number == "LOT-000001"


from app.schemas.science import RunCreate, RunResponse, RunUpdate


def test_run_create_default_produces_lot_false():
    payload = RunCreate(name="r", project_id="00000000-0000-0000-0000-000000000001")
    assert payload.produces_lot is False


def test_run_create_accepts_produces_lot_true():
    payload = RunCreate(
        name="r",
        project_id="00000000-0000-0000-0000-000000000001",
        produces_lot=True,
        lot_number="LOT-000001",
    )
    assert payload.produces_lot is True


def test_run_update_produces_lot_optional():
    payload = RunUpdate(produces_lot=True)
    assert payload.produces_lot is True
    payload2 = RunUpdate()
    assert payload2.produces_lot is None

"""Tests for services/equipment/calibration.get_calibration_status (F-0092)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization
from app.models.equipment import Equipment
from app.services.equipment.calibration import (
    CALIBRATION_DUE_SOON_DAYS,
    get_calibration_status,
)


def _eq(org_id, site_id, name, *, days_offset=None, archived=False):
    cal = (
        None
        if days_offset is None
        else date.today() + timedelta(days=days_offset)
    )
    return Equipment(
        organization_id=org_id,
        site_id=site_id,
        name=name,
        next_calibration_date=cal,
        archived_at=datetime.now(timezone.utc) if archived else None,
    )


@pytest.mark.asyncio
async def test_partitions_by_boundary_dates(
    db_session: AsyncSession, test_org: Organization, default_site_id: str
):
    rows = [
        _eq(test_org.id, default_site_id, "Overdue", days_offset=-1),
        _eq(test_org.id, default_site_id, "DueToday", days_offset=0),
        _eq(test_org.id, default_site_id, "DueEdge",
            days_offset=CALIBRATION_DUE_SOON_DAYS),
        _eq(test_org.id, default_site_id, "Beyond",
            days_offset=CALIBRATION_DUE_SOON_DAYS + 1),
        _eq(test_org.id, default_site_id, "NoDate", days_offset=None),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    status = await get_calibration_status(db_session, test_org.id)
    assert [i.name for i in status.overdue] == ["Overdue"]
    # due_soon is also sorted ascending (soonest first), per the docstring.
    assert [i.name for i in status.due_soon] == ["DueToday", "DueEdge"]


@pytest.mark.asyncio
async def test_excludes_archived_equipment(
    db_session: AsyncSession, test_org: Organization, default_site_id: str
):
    db_session.add(
        _eq(test_org.id, default_site_id, "ArchivedOverdue",
            days_offset=-5, archived=True)
    )
    await db_session.flush()
    status = await get_calibration_status(db_session, test_org.id)
    assert status.overdue == []


@pytest.mark.asyncio
async def test_overdue_sorted_most_urgent_first(
    db_session: AsyncSession, test_org: Organization, default_site_id: str
):
    db_session.add_all([
        _eq(test_org.id, default_site_id, "Recent", days_offset=-2),
        _eq(test_org.id, default_site_id, "Ancient", days_offset=-90),
    ])
    await db_session.flush()
    status = await get_calibration_status(db_session, test_org.id)
    assert [i.name for i in status.overdue] == ["Ancient", "Recent"]

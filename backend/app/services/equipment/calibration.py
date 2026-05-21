"""Org equipment calibration status for the dashboard (F-0092).

The 30-day window here is a calibration-*planning* horizon — deliberately
distinct from the run-start flow's 14-day "imminent" warning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.schemas.dashboard import CalibrationItem, CalibrationStatus

CALIBRATION_DUE_SOON_DAYS = 30


async def get_calibration_status(
    db: AsyncSession, org_id: UUID
) -> CalibrationStatus:
    """Partition the org's non-archived equipment into overdue / due-soon.

    Equipment with a null calibration date, or one more than
    ``CALIBRATION_DUE_SOON_DAYS`` out, is excluded. Both lists are ordered by
    ``next_calibration_date`` ascending (most urgent first).
    """
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=CALIBRATION_DUE_SOON_DAYS)

    result = await db.execute(
        select(Equipment)
        .where(
            Equipment.organization_id == org_id,
            Equipment.archived_at.is_(None),
            Equipment.next_calibration_date.is_not(None),
        )
        .order_by(Equipment.next_calibration_date.asc())
    )

    overdue: list[CalibrationItem] = []
    due_soon: list[CalibrationItem] = []
    for eq in result.scalars().all():
        cal_date = eq.next_calibration_date
        if cal_date < today:
            state = "overdue"
        elif cal_date <= horizon:
            state = "due_soon"
        else:
            continue
        item = CalibrationItem(
            equipment_id=eq.id,
            name=eq.name,
            site_name=eq.site.name if eq.site else None,
            next_calibration_date=cal_date,
            state=state,
        )
        (overdue if state == "overdue" else due_soon).append(item)

    return CalibrationStatus(overdue=overdue, due_soon=due_soon)

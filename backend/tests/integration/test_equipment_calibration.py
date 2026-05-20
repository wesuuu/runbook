"""Equipment calibration field updates (F-0087 Task 21)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.iam import Organization


@pytest.fixture
async def test_equipment(db_session: AsyncSession, test_org: Organization) -> Equipment:
    """A bare equipment row for calibration field tests."""
    eq = Equipment(
        organization_id=test_org.id,
        name="Calibration Test Centrifuge",
        equipment_type="Centrifuge",
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest.mark.asyncio
async def test_equipment_accepts_calibration_fields(
    client: AsyncClient,
    auth_headers: dict,
    test_equipment: Equipment,
):
    """update_equipment persists serial + calibration metadata."""
    res = await client.put(
        f"/iam/equipment/{test_equipment.id}",
        headers=auth_headers,
        json={
            "serial_number": "SN-12345",
            "last_calibration_date": "2026-01-15",
            "next_calibration_date": "2026-07-15",
            "calibration_certificate_path": "uploads/cert.pdf",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["serial_number"] == "SN-12345"
    assert body["last_calibration_date"] == "2026-01-15"
    assert body["next_calibration_date"] == "2026-07-15"
    assert body["calibration_certificate_path"] == "uploads/cert.pdf"


@pytest.mark.asyncio
async def test_equipment_calibration_fields_audited(
    client: AsyncClient,
    auth_headers: dict,
    test_equipment: Equipment,
    db_session: AsyncSession,
):
    """Calibration updates appear in the audit log changes payload."""
    from sqlalchemy import select

    from app.models.execution import AuditLog

    res = await client.put(
        f"/iam/equipment/{test_equipment.id}",
        headers=auth_headers,
        json={
            "serial_number": "SN-AUDIT",
            "next_calibration_date": "2027-01-01",
        },
    )
    assert res.status_code == 200, res.text

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == test_equipment.id,
            AuditLog.entity_type == "equipment",
            AuditLog.action == "update",
        )
    )
    audit = result.scalar_one_or_none()
    assert audit is not None
    assert "serial_number" in audit.changes
    assert audit.changes["serial_number"] == "SN-AUDIT"
    assert "next_calibration_date" in audit.changes

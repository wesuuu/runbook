import pytest
from fastapi import HTTPException

from app.schemas.equipment import (EquipmentCreate, EquipmentStatus,
                                   EquipmentUpdate)
from app.services.equipment import registry


@pytest.mark.asyncio
async def test_create_equipment_requires_valid_site(
    db_session, test_org, test_user, sample_site
):
    eq = await registry.create_equipment(
        db_session,
        org_id=test_org.id,
        payload=EquipmentCreate(
            name="Balance", site_id=sample_site.id, tags=["GLP", "glp"]
        ),
        actor_id=test_user.id,
        can_set_restricted=True,
    )
    assert eq.tags == ["glp"]
    assert eq.status == "ACTIVE"


@pytest.mark.asyncio
async def test_create_equipment_soft_drops_restricted_when_not_authorized(
    db_session, test_org, test_user, sample_site
):
    eq = await registry.create_equipment(
        db_session,
        org_id=test_org.id,
        payload=EquipmentCreate(
            name="X",
            site_id=sample_site.id,
            manufacturer="Mettler",
            model="ME204",
            serial_number="MT-001",
            last_calibration_date="2026-01-01",
            status=EquipmentStatus.MAINTENANCE,
        ),
        actor_id=test_user.id,
        can_set_restricted=False,
    )
    assert eq.manufacturer is None
    assert eq.model is None
    assert eq.serial_number is None
    assert eq.last_calibration_date is None
    assert eq.status == "ACTIVE"


@pytest.mark.asyncio
async def test_create_equipment_cross_org_site_rejected(
    db_session, test_org, test_user, other_org_site
):
    with pytest.raises(HTTPException) as exc:
        await registry.create_equipment(
            db_session,
            org_id=test_org.id,
            payload=EquipmentCreate(name="X", site_id=other_org_site.id),
            actor_id=test_user.id,
            can_set_restricted=True,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_SITE_CROSS_ORG"


@pytest.mark.asyncio
async def test_list_filters_by_site_status_search_tag(
    db_session, test_org, test_user, sample_site
):
    a = await registry.create_equipment(
        db_session,
        org_id=test_org.id,
        payload=EquipmentCreate(name="HPLC-1", site_id=sample_site.id, tags=["qc"]),
        actor_id=test_user.id,
        can_set_restricted=True,
    )
    b = await registry.create_equipment(
        db_session,
        org_id=test_org.id,
        payload=EquipmentCreate(
            name="Balance", site_id=sample_site.id, tags=["analytical"]
        ),
        actor_id=test_user.id,
        can_set_restricted=True,
    )
    out = await registry.list_equipment(db_session, test_org.id, tag="qc")
    assert [e.id for e in out] == [a.id]

    out = await registry.list_equipment(db_session, test_org.id, q="balance")
    assert [e.id for e in out] == [b.id]


@pytest.mark.asyncio
async def test_archive_equipment(db_session, test_org, test_user, sample_site):
    eq = await registry.create_equipment(
        db_session,
        org_id=test_org.id,
        payload=EquipmentCreate(name="X", site_id=sample_site.id),
        actor_id=test_user.id,
        can_set_restricted=True,
    )
    await registry.archive_equipment(db_session, eq, actor_id=test_user.id)
    await db_session.refresh(eq)
    assert eq.archived_at is not None


def test_restricted_fields_set():
    assert "manufacturer" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "model" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "serial_number" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "status" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "install_date" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "last_calibration_date" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "next_calibration_date" in registry.RESTRICTED_EQUIPMENT_FIELDS
    for f in ("name", "equipment_type", "room", "location", "description", "tags"):
        assert f not in registry.RESTRICTED_EQUIPMENT_FIELDS

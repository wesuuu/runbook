import pytest
from sqlalchemy import select, text

from app.models.equipment import Equipment
from app.models.sites import Site


@pytest.mark.asyncio
async def test_every_equipment_row_has_site_id(db_session):
    rows = (await db_session.execute(select(Equipment))).scalars().all()
    for row in rows:
        assert row.site_id is not None
        # Site belongs to the same org.
        site = await db_session.get(Site, row.site_id)
        assert site.organization_id == row.organization_id


@pytest.mark.asyncio
async def test_every_org_has_exactly_one_default_site(db_session):
    org_count = (
        await db_session.execute(text("SELECT COUNT(*) FROM organizations"))
    ).scalar_one()
    default_count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM sites WHERE is_default = true")
        )
    ).scalar_one()
    assert default_count == org_count

    duplicates = (
        await db_session.execute(
            text(
                """
        SELECT organization_id, COUNT(*) FROM sites
        WHERE is_default = true
        GROUP BY organization_id HAVING COUNT(*) > 1
    """
            )
        )
    ).all()
    assert duplicates == []


@pytest.mark.asyncio
async def test_equipment_site_id_is_not_null(db_session):
    result = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='equipment' AND column_name='site_id'"
        )
    )
    nullable = result.scalar_one()
    assert nullable == "NO"


@pytest.mark.asyncio
async def test_site_manager_grants_table_exists(db_session):
    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'site_manager_grants'"
        )
    )
    assert result.scalar_one() == 1

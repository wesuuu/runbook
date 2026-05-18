import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.science import Equipment
from app.schemas.sites import SiteArchiveRequest, SiteCreate, SiteUpdate
from app.services.sites import crud


@pytest.mark.asyncio
async def test_create_site(db_session, test_org, test_user):
    site = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="South Bay HQ"),
        actor_id=test_user.id,
    )
    assert site.name == "South Bay HQ"
    assert site.created_by_id == test_user.id


@pytest.mark.asyncio
async def test_create_site_name_conflict(db_session, test_org, test_user):
    await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="HQ"),
        actor_id=test_user.id,
    )
    with pytest.raises(HTTPException) as exc:
        await crud.create_site(
            db_session,
            org_id=test_org.id,
            payload=SiteCreate(name="HQ"),
            actor_id=test_user.id,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SITE_NAME_CONFLICT"


@pytest.mark.asyncio
async def test_list_sites_excludes_archived_by_default(db_session, test_org, test_user):
    import datetime

    s = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Archived"),
        actor_id=test_user.id,
    )
    s.archived_at = datetime.datetime.now(datetime.timezone.utc)
    await db_session.commit()
    listed = await crud.list_sites(db_session, test_org.id)
    assert all(x.archived_at is None for x in listed)


@pytest.mark.asyncio
async def test_update_site(db_session, test_org, test_user):
    s = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="HQ"),
        actor_id=test_user.id,
    )
    s2 = await crud.update_site(
        db_session,
        s,
        payload=SiteUpdate(description="hello"),
        actor_id=test_user.id,
    )
    assert s2.description == "hello"


@pytest.mark.asyncio
async def test_archive_site_moves_equipment_to_default(
    db_session, test_org, test_user, make_equipment
):
    src = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Old Lab"),
        actor_id=test_user.id,
    )
    dst = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="New Lab"),
        actor_id=test_user.id,
    )
    e1 = await make_equipment(site_id=src.id)
    e2 = await make_equipment(site_id=src.id)

    await crud.archive_site(
        db_session,
        src,
        default_move_to=dst.id,
        overrides={},
        reason="consolidate",
        actor_id=test_user.id,
    )

    await db_session.refresh(e1)
    await db_session.refresh(e2)
    assert e1.site_id == dst.id
    assert e2.site_id == dst.id

    await db_session.refresh(src)
    assert src.archived_at is not None
    assert src.archive_reason == "consolidate"


@pytest.mark.asyncio
async def test_archive_site_honors_overrides(
    db_session, test_org, test_user, make_equipment
):
    src = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Old Lab"),
        actor_id=test_user.id,
    )
    dst_a = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Lab A"),
        actor_id=test_user.id,
    )
    dst_b = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Lab B"),
        actor_id=test_user.id,
    )
    e1 = await make_equipment(site_id=src.id)
    e2 = await make_equipment(site_id=src.id)

    await crud.archive_site(
        db_session,
        src,
        default_move_to=dst_a.id,
        overrides={e2.id: dst_b.id},
        reason="x",
        actor_id=test_user.id,
    )
    await db_session.refresh(e1)
    await db_session.refresh(e2)
    assert e1.site_id == dst_a.id
    assert e2.site_id == dst_b.id


@pytest.mark.asyncio
async def test_archive_default_site_forbidden(db_session, test_org, test_user):
    from app.services.sites.defaults import ensure_default_site

    default = await ensure_default_site(db_session, test_org.id, actor_id=test_user.id)
    other = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Other"),
        actor_id=test_user.id,
    )
    with pytest.raises(HTTPException) as exc:
        await crud.archive_site(
            db_session,
            default,
            default_move_to=other.id,
            overrides={},
            reason="x",
            actor_id=test_user.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVE_DEFAULT_FORBIDDEN"


@pytest.mark.asyncio
async def test_archive_site_rejects_self_as_destination(
    db_session, test_org, test_user
):
    s = await crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="X"),
        actor_id=test_user.id,
    )
    with pytest.raises(HTTPException) as exc:
        await crud.archive_site(
            db_session,
            s,
            default_move_to=s.id,
            overrides={},
            reason="x",
            actor_id=test_user.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVE_SELF_DESTINATION"

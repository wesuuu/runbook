import pytest
from fastapi import HTTPException

from app.schemas.sites import SiteCreate, SiteUpdate
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

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.models.iam import OrganizationMember, User
from app.models.sites import Site
from app.services.sites.grants import (
    grant_site_manager,
    list_grants_for_site,
    list_managed_sites_for_user,
    revoke_site_manager,
    user_has_grant,
)


@pytest.fixture
async def test_site(db_session, test_org):
    site = Site(
        organization_id=test_org.id,
        name=f"Site-{test_org.id}",
        is_default=False,
    )
    db_session.add(site)
    await db_session.flush()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def archived_site(db_session, test_org):
    site = Site(
        organization_id=test_org.id,
        name=f"Archived-{test_org.id}",
        is_default=False,
        archived_at=datetime.now(timezone.utc),
    )
    db_session.add(site)
    await db_session.flush()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_admin(db_session, test_org):
    admin = User(
        email=f"admin-{test_org.id}@example.com",
        hashed_password=hash_password("adminpass"),
        full_name="Admin User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(admin)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=test_org.id,
            user_id=admin.id,
            roles=["ADMIN"],
        )
    )
    await db_session.flush()
    await db_session.refresh(admin)
    return admin


@pytest.mark.asyncio
async def test_grant_and_list_for_site(db_session, test_site, test_user, test_admin):
    grant = await grant_site_manager(
        db_session,
        site=test_site,
        user_id=test_user.id,
        granted_by_id=test_admin.id,
    )
    grants = await list_grants_for_site(db_session, test_site.id)
    assert [g.id for g in grants] == [grant.id]


@pytest.mark.asyncio
async def test_grant_is_idempotent(db_session, test_site, test_user, test_admin):
    g1 = await grant_site_manager(
        db_session,
        site=test_site,
        user_id=test_user.id,
        granted_by_id=test_admin.id,
    )
    g2 = await grant_site_manager(
        db_session,
        site=test_site,
        user_id=test_user.id,
        granted_by_id=test_admin.id,
    )
    assert g1.id == g2.id


@pytest.mark.asyncio
async def test_revoke_clears_grant(db_session, test_site, test_user, test_admin):
    await grant_site_manager(
        db_session,
        site=test_site,
        user_id=test_user.id,
        granted_by_id=test_admin.id,
    )
    await revoke_site_manager(
        db_session,
        site_id=test_site.id,
        user_id=test_user.id,
        actor_id=test_admin.id,
    )
    assert await user_has_grant(db_session, test_site.id, test_user.id) is False


@pytest.mark.asyncio
async def test_list_managed_sites_for_user_excludes_archived(
    db_session, test_user, test_admin, test_site, archived_site
):
    # Grant on active site via service
    await grant_site_manager(
        db_session,
        site=test_site,
        user_id=test_user.id,
        granted_by_id=test_admin.id,
    )
    # Insert grant on archived site directly (bypassing the archive guard)
    from app.models.sites import SiteManagerGrant

    db_session.add(
        SiteManagerGrant(
            organization_id=archived_site.organization_id,
            site_id=archived_site.id,
            user_id=test_user.id,
            granted_by_id=test_admin.id,
        )
    )
    await db_session.flush()

    out = await list_managed_sites_for_user(
        db_session,
        test_user.id,
        include_archived=False,
    )
    assert [m.site.id for m in out] == [test_site.id]


@pytest.mark.asyncio
async def test_grant_rejects_archived_site(
    db_session, archived_site, test_user, test_admin
):
    with pytest.raises(HTTPException) as exc:
        await grant_site_manager(
            db_session,
            site=archived_site,
            user_id=test_user.id,
            granted_by_id=test_admin.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVED"

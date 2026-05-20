import pytest

from app.core.security import hash_password
from app.models.iam import OrganizationMember, User
from app.models.sites import Site, SiteManagerGrant
from app.services.permissions.equipment import (
    user_can_edit_restricted_equipment,
    user_can_move_equipment,
    user_can_rename_site,
)


async def _make_member(db, *, org_id, roles, email):
    user = User(
        email=email,
        full_name=email.split("@")[0],
        hashed_password=hash_password("x"),
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            roles=roles,
            archived=False,
        )
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _make_site(db, *, org_id, name="Site A", is_default=False):
    site = Site(organization_id=org_id, name=name, is_default=is_default)
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


async def _grant(db, *, site, user_id):
    g = SiteManagerGrant(
        organization_id=site.organization_id,
        site_id=site.id,
        user_id=user_id,
    )
    db.add(g)
    await db.commit()
    return g


@pytest.mark.asyncio
async def test_admin_bypasses_grant_check(db_session, test_org):
    admin = await _make_member(
        db_session,
        org_id=test_org.id,
        roles=["ADMIN"],
        email=f"admin-{test_org.id}@x.com",
    )
    site = await _make_site(db_session, org_id=test_org.id)
    assert (
        await user_can_edit_restricted_equipment(
            db_session,
            user_id=admin.id,
            org_id=test_org.id,
            site_id=site.id,
        )
        is True
    )


@pytest.mark.asyncio
async def test_site_manager_with_grant_can_edit(db_session, test_org):
    mgr = await _make_member(
        db_session,
        org_id=test_org.id,
        roles=["MEMBER", "SITE_MANAGER"],
        email=f"mgr-{test_org.id}@x.com",
    )
    site = await _make_site(db_session, org_id=test_org.id, name="Site G")
    await _grant(db_session, site=site, user_id=mgr.id)
    assert (
        await user_can_edit_restricted_equipment(
            db_session,
            user_id=mgr.id,
            org_id=test_org.id,
            site_id=site.id,
        )
        is True
    )


@pytest.mark.asyncio
async def test_site_manager_without_grant_cannot_edit(db_session, test_org):
    mgr = await _make_member(
        db_session,
        org_id=test_org.id,
        roles=["MEMBER", "SITE_MANAGER"],
        email=f"mgr2-{test_org.id}@x.com",
    )
    site_a = await _make_site(db_session, org_id=test_org.id, name="A")
    site_b = await _make_site(db_session, org_id=test_org.id, name="B")
    await _grant(db_session, site=site_a, user_id=mgr.id)
    # No grant on site_b
    assert (
        await user_can_edit_restricted_equipment(
            db_session,
            user_id=mgr.id,
            org_id=test_org.id,
            site_id=site_b.id,
        )
        is False
    )


@pytest.mark.asyncio
async def test_move_requires_grants_on_both_sites(db_session, test_org):
    mgr = await _make_member(
        db_session,
        org_id=test_org.id,
        roles=["MEMBER", "SITE_MANAGER"],
        email=f"mgr3-{test_org.id}@x.com",
    )
    src = await _make_site(db_session, org_id=test_org.id, name="Src")
    dst = await _make_site(db_session, org_id=test_org.id, name="Dst")
    await _grant(db_session, site=src, user_id=mgr.id)
    ok, missing = await user_can_move_equipment(
        db_session,
        user_id=mgr.id,
        org_id=test_org.id,
        from_site_id=src.id,
        to_site_id=dst.id,
    )
    assert ok is False
    assert dst.id in missing
    assert src.id not in missing


@pytest.mark.asyncio
async def test_member_without_role_cannot_rename(db_session, test_org):
    user = await _make_member(
        db_session,
        org_id=test_org.id,
        roles=["MEMBER"],
        email=f"plain-{test_org.id}@x.com",
    )
    site = await _make_site(db_session, org_id=test_org.id, name="R")
    assert (
        await user_can_rename_site(
            db_session,
            user_id=user.id,
            org_id=test_org.id,
            site_id=site.id,
        )
        is False
    )

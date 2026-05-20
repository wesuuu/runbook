# backend/tests/unit/test_site_model.py
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.iam import Organization
from app.models.sites import Site


async def _make_bare_org(db_session, name="Bare Org"):
    """Create an org without the test_org fixture's auto-default-site so we
    can exercise the partial unique constraint cleanly.
    """
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    return org


@pytest.mark.asyncio
async def test_site_minimal_fields(db_session, test_org):
    site = Site(
        organization_id=test_org.id,
        name="South Bay HQ",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    assert site.id is not None
    assert site.archived_at is None
    assert site.created_at is not None


@pytest.mark.asyncio
async def test_site_partial_unique_active_name(db_session, test_org):
    s1 = Site(organization_id=test_org.id, name="HQ")
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=test_org.id, name="HQ")
    db_session.add(s2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_site_name_reused_after_archive(db_session, test_org):
    s1 = Site(
        organization_id=test_org.id,
        name="HQ",
        archived_at=datetime.now(timezone.utc),
    )
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=test_org.id, name="HQ")
    db_session.add(s2)
    await db_session.commit()  # should NOT raise
    assert s2.id != s1.id


@pytest.mark.asyncio
async def test_site_is_default_default_false(db_session, test_org):
    s = Site(organization_id=test_org.id, name="HQ")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    assert s.is_default is False


@pytest.mark.asyncio
async def test_only_one_default_site_per_org(db_session):
    org = await _make_bare_org(db_session, name="Default-Unique Org")

    s1 = Site(organization_id=org.id, name="HQ", is_default=True)
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=org.id, name="Lab B", is_default=True)
    db_session.add(s2)
    with pytest.raises(IntegrityError):
        await db_session.commit()  # partial unique violation

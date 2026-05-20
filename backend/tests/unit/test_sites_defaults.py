import pytest

from app.services.sites.defaults import (
    DEFAULT_SITE_NAME,
    ensure_default_site,
    is_default_site,
)


@pytest.mark.asyncio
async def test_ensure_default_site_creates(db_session, test_org, test_user):
    site = await ensure_default_site(db_session, test_org.id, actor_id=test_user.id)
    assert site.name == DEFAULT_SITE_NAME
    assert site.organization_id == test_org.id


@pytest.mark.asyncio
async def test_ensure_default_site_idempotent(db_session, test_org, test_user):
    s1 = await ensure_default_site(db_session, test_org.id, actor_id=test_user.id)
    s2 = await ensure_default_site(db_session, test_org.id, actor_id=test_user.id)
    assert s1.id == s2.id


@pytest.mark.asyncio
async def test_is_default_site_reads_column_not_name(db_session, test_org, test_user):
    site = await ensure_default_site(db_session, test_org.id, actor_id=test_user.id)
    assert site.is_default is True
    assert is_default_site(site) is True

    site.name = "HQ"
    assert is_default_site(site) is True

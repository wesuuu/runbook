import pytest

from app.services.sites.crud import list_sites
from app.services.sites.defaults import DEFAULT_SITE_NAME


@pytest.mark.asyncio
async def test_default_site_created_on_org_create(client, auth_headers, db_session):
    res = await client.post(
        "/iam/organizations",
        json={"name": "Acme PD"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    org_id = res.json()["id"]

    sites = await list_sites(db_session, org_id)
    names = [s.name for s in sites]
    assert DEFAULT_SITE_NAME in names

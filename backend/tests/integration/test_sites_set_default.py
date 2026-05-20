import pytest


@pytest.mark.asyncio
async def test_set_default_swaps_default_atomically(
    authed_admin_client, default_site_id, unmanaged_site
):
    """ADMIN promotes a non-default site → previous default loses the bit,
    new site holds it, and exactly one default remains."""
    res = await authed_admin_client.post(f"/sites/{unmanaged_site.id}/set-default")
    assert res.status_code == 200
    assert res.json()["is_default"] is True

    listing = (await authed_admin_client.get("/sites")).json()
    defaults = [s for s in listing if s["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == str(unmanaged_site.id)

    # Old default explicitly cleared.
    prev = next(s for s in listing if s["id"] == default_site_id)
    assert prev["is_default"] is False


@pytest.mark.asyncio
async def test_set_default_idempotent(authed_admin_client, default_site_id):
    """Setting the current default to default again is a no-op (200)."""
    res = await authed_admin_client.post(f"/sites/{default_site_id}/set-default")
    assert res.status_code == 200
    assert res.json()["is_default"] is True


@pytest.mark.asyncio
async def test_set_default_member_403(authed_member_client, unmanaged_site):
    res = await authed_member_client.post(f"/sites/{unmanaged_site.id}/set-default")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_set_default_site_manager_403(authed_site_manager_client, managed_site):
    """SITE_MANAGER role + grant is NOT enough — only ADMIN can promote."""
    res = await authed_site_manager_client.post(f"/sites/{managed_site.id}/set-default")
    assert res.status_code == 403

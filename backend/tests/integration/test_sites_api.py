import pytest


@pytest.mark.asyncio
async def test_list_sites_any_member(authed_member_client):
    res = await authed_member_client.get("/sites")
    assert res.status_code == 200
    assert any(s["name"] == "Default Site" for s in res.json())


@pytest.mark.asyncio
async def test_create_site_member_403(authed_member_client):
    res = await authed_member_client.post("/sites", json={"name": "X"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_site_site_manager_403(authed_site_manager_client):
    res = await authed_site_manager_client.post("/sites", json={"name": "X"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_site_admin_ok(authed_admin_client):
    res = await authed_admin_client.post("/sites", json={"name": "South Bay"})
    assert res.status_code == 200
    assert res.json()["name"] == "South Bay"


@pytest.mark.asyncio
async def test_rename_site_by_site_manager_with_grant(
    authed_site_manager_client, managed_site
):
    res = await authed_site_manager_client.patch(
        f"/sites/{managed_site.id}", json={"name": "Renamed"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_rename_site_by_site_manager_without_grant(
    authed_site_manager_client, unmanaged_site
):
    res = await authed_site_manager_client.patch(
        f"/sites/{unmanaged_site.id}", json={"name": "Nope"}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_archive_site_member_403(authed_site_manager_client, managed_site):
    res = await authed_site_manager_client.request(
        "DELETE",
        f"/sites/{managed_site.id}",
        json={
            "default_move_to": "00000000-0000-0000-0000-000000000000",
            "reason": "test",
        },
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_archive_site_default_forbidden(authed_admin_client):
    list_res = await authed_admin_client.get("/sites")
    default_id = next(s["id"] for s in list_res.json() if s["is_default"])
    other = (await authed_admin_client.post("/sites", json={"name": "Other"})).json()
    res = await authed_admin_client.request(
        "DELETE",
        f"/sites/{default_id}",
        json={"default_move_to": other["id"], "reason": "no"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "SITE_ARCHIVE_DEFAULT_FORBIDDEN"


@pytest.mark.asyncio
async def test_archive_site_needs_move_to(authed_admin_client):
    a = (await authed_admin_client.post("/sites", json={"name": "A"})).json()
    res = await authed_admin_client.request("DELETE", f"/sites/{a['id']}", json={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_site_managers_admin_only(
    authed_admin_client, authed_member_client, managed_site
):
    res = await authed_admin_client.get(f"/sites/{managed_site.id}/managers")
    assert res.status_code == 200

    res = await authed_member_client.get(f"/sites/{managed_site.id}/managers")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_grant_site_manager_admin_only(
    authed_admin_client, authed_member_client, managed_site, grantee_user
):
    res = await authed_member_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(grantee_user.id)},
    )
    assert res.status_code == 403

    res = await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(grantee_user.id)},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_revoke_site_manager_admin_only(
    authed_admin_client, managed_site, grantee_user
):
    await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(grantee_user.id)},
    )
    res = await authed_admin_client.delete(
        f"/sites/{managed_site.id}/managers/{grantee_user.id}"
    )
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_managed_sites_for_user(authed_admin_client, managed_site, grantee_user):
    await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(grantee_user.id)},
    )
    res = await authed_admin_client.get(f"/users/{grantee_user.id}/managed-sites")
    assert res.status_code == 200
    assert any(m["site"]["id"] == str(managed_site.id) for m in res.json())


@pytest.mark.asyncio
async def test_get_my_managed_sites_returns_grants_for_caller(
    authed_site_manager_client, managed_site, authed_admin_client, test_org
):
    """Site manager with grants on 2 sites calls /users/me/managed-sites and
    gets 2 entries. The existing `managed_site` fixture already grants the
    site_manager_user on one site; we add a second grant on a new site."""
    # Create a second site and grant the site_manager_user on it.
    second = (
        await authed_admin_client.post("/sites", json={"name": "Second Site"})
    ).json()
    # Discover the site_manager_user id by listing managers on managed_site
    managers = (
        await authed_admin_client.get(f"/sites/{managed_site.id}/managers")
    ).json()
    site_manager_user_id = managers[0]["user_id"]
    await authed_admin_client.post(
        f"/sites/{second['id']}/managers",
        json={"user_id": site_manager_user_id},
    )

    res = await authed_site_manager_client.get("/users/me/managed-sites")
    assert res.status_code == 200
    site_ids = {m["site"]["id"] for m in res.json()}
    assert str(managed_site.id) in site_ids
    assert second["id"] in site_ids
    assert len(res.json()) == 2


@pytest.mark.asyncio
async def test_get_my_managed_sites_empty_for_member_without_grants(
    authed_member_client,
):
    res = await authed_member_client.get("/users/me/managed-sites")
    assert res.status_code == 200
    assert res.json() == []

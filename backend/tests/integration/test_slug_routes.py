"""Integration tests for F-0091 slug assignment and by-slug lookup."""

import pytest


@pytest.mark.asyncio
async def test_create_protocol_assigns_slug(client, auth_headers, test_org):
    resp = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "buffer-prep"


@pytest.mark.asyncio
async def test_duplicate_protocol_name_is_rejected(client, auth_headers, test_org):
    body = {"name": "Buffer Prep", "organization_id": str(test_org.id)}
    first = await client.post("/protocols", json=body, headers=auth_headers)
    assert first.status_code == 201
    dup = await client.post(
        "/protocols",
        json={"name": "buffer  prep", "organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_protocol_by_slug(client, auth_headers, test_org):
    created = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    pid = created.json()["id"]
    resp = await client.get("/protocols/by-slug/buffer-prep", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


@pytest.mark.asyncio
async def test_get_protocol_by_slug_unknown_returns_404(client, auth_headers):
    resp = await client.get("/protocols/by-slug/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_protocol_rename_reslugs(client, auth_headers, test_org):
    created = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    pid = created.json()["id"]
    renamed = await client.put(
        f"/protocols/{pid}", json={"name": "Wash Buffer"}, headers=auth_headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "wash-buffer"
    assert (
        await client.get("/protocols/by-slug/wash-buffer", headers=auth_headers)
    ).status_code == 200


@pytest.mark.asyncio
async def test_create_project_assigns_slug(client, auth_headers):
    resp = await client.post(
        "/projects/", json={"name": "CHO Cell Line Dev"}, headers=auth_headers
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "cho-cell-line-dev"


@pytest.mark.asyncio
async def test_duplicate_project_name_is_rejected(client, auth_headers):
    await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    dup = await client.post(
        "/projects/", json={"name": "cho  line"}, headers=auth_headers
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_project_by_slug(client, auth_headers):
    created = await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )
    resp = await client.get("/projects/by-slug/cho-line", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created.json()["id"]


@pytest.mark.asyncio
async def test_project_rename_reslugs(client, auth_headers):
    created = await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )
    pid = created.json()["id"]
    renamed = await client.put(
        f"/projects/{pid}", json={"name": "HEK Line"}, headers=auth_headers
    )
    assert renamed.json()["slug"] == "hek-line"

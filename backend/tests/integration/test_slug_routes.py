"""Integration tests for F-0091 slug assignment and by-slug lookup."""

import io
from unittest.mock import patch

import pytest

# Minimal valid PDF payload — text/plain is no longer an allowed document
# type (TD-0085), so document upload tests use a PDF with real magic bytes.
_PDF_CONTENT = b"%PDF-1.4\n%minimal\n"


@pytest.fixture
def mock_document_processor():
    """Stub the background handler so document uploads don't spawn jobs."""

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            pass

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        yield


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


@pytest.mark.asyncio
async def test_create_run_assigns_slug_and_project_slug(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    resp = await client.post(
        "/runs",
        json={"name": "Seeding 2026-05-12", "project_id": proj["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "seeding-2026-05-12"
    assert body["project_slug"] == "cho-line"


@pytest.mark.asyncio
async def test_duplicate_run_name_in_same_project_is_rejected(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    body = {"name": "Seeding", "project_id": proj["id"]}
    assert (
        await client.post("/runs", json=body, headers=auth_headers)
    ).status_code == 201
    dup = await client.post("/runs", json=body, headers=auth_headers)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_same_run_name_allowed_in_different_projects(client, auth_headers):
    p1 = (
        await client.post("/projects/", json={"name": "P1"}, headers=auth_headers)
    ).json()
    p2 = (
        await client.post("/projects/", json={"name": "P2"}, headers=auth_headers)
    ).json()
    body1 = {"name": "Seeding", "project_id": p1["id"]}
    body2 = {"name": "Seeding", "project_id": p2["id"]}
    assert (
        await client.post("/runs", json=body1, headers=auth_headers)
    ).status_code == 201
    assert (
        await client.post("/runs", json=body2, headers=auth_headers)
    ).status_code == 201


@pytest.mark.asyncio
async def test_get_run_by_slug(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    created = (
        await client.post(
            "/runs",
            json={"name": "Seeding", "project_id": proj["id"]},
            headers=auth_headers,
        )
    ).json()
    resp = await client.get("/runs/by-slug/cho-line/seeding", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_run_by_slug_unknown_returns_404(client, auth_headers):
    await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    # Unknown run slug under a known project slug.
    resp = await client.get(
        "/runs/by-slug/cho-line/does-not-exist", headers=auth_headers
    )
    assert resp.status_code == 404
    # Unknown project slug.
    resp = await client.get(
        "/runs/by-slug/no-such-project/seeding", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_by_slug_is_org_scoped(client, auth_headers, second_auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    await client.post(
        "/runs",
        json={"name": "Seeding", "project_id": proj["id"]},
        headers=auth_headers,
    )
    # The run is reachable for the owning org's user.
    resp = await client.get("/runs/by-slug/cho-line/seeding", headers=auth_headers)
    assert resp.status_code == 200
    # A user in a different org cannot reach it via the by-slug route.
    resp = await client.get(
        "/runs/by-slug/cho-line/seeding", headers=second_auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_rename_reslugs(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    created = (
        await client.post(
            "/runs",
            json={"name": "Seeding", "project_id": proj["id"]},
            headers=auth_headers,
        )
    ).json()
    renamed = await client.put(
        f"/runs/{created['id']}", json={"name": "Expansion"}, headers=auth_headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "expansion"
    resp = await client.get("/runs/by-slug/cho-line/expansion", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_create_experiment_assigns_slug_and_project_slug(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    resp = await client.post(
        "/experiments",
        json={"name": "Passage 3", "project_id": proj["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "passage-3"
    assert body["project_slug"] == "cho-line"


@pytest.mark.asyncio
async def test_duplicate_experiment_name_in_project_is_rejected(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    body = {"name": "Passage 3", "project_id": proj["id"]}
    assert (
        await client.post("/experiments", json=body, headers=auth_headers)
    ).status_code == 201
    dup = await client.post("/experiments", json=body, headers=auth_headers)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_experiment_by_slug(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    created = (
        await client.post(
            "/experiments",
            json={"name": "Passage 3", "project_id": proj["id"]},
            headers=auth_headers,
        )
    ).json()
    resp = await client.get(
        "/experiments/by-slug/cho-line/passage-3", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_experiment_rename_reslugs(client, auth_headers):
    proj = (
        await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    ).json()
    created = (
        await client.post(
            "/experiments",
            json={"name": "Passage 3", "project_id": proj["id"]},
            headers=auth_headers,
        )
    ).json()
    renamed = await client.put(
        f"/experiments/{created['id']}",
        json={"name": "Passage 4"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "passage-4"
    resp = await client.get(
        "/experiments/by-slug/cho-line/passage-4", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_upload_document_assigns_slug(
    client, auth_headers, mock_document_processor
):
    resp = await client.post(
        "/library/documents",
        data={"title": "SOP Aseptic Technique"},
        files={"file": ("sop.pdf", io.BytesIO(_PDF_CONTENT), "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "sop-aseptic-technique"


@pytest.mark.asyncio
async def test_duplicate_document_title_is_rejected(
    client, auth_headers, mock_document_processor
):
    def _upload():
        return client.post(
            "/library/documents",
            data={"title": "SOP One"},
            files={"file": ("sop.pdf", io.BytesIO(_PDF_CONTENT), "application/pdf")},
            headers=auth_headers,
        )

    assert (await _upload()).status_code == 201
    dup = await _upload()
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_document_by_slug(client, auth_headers, mock_document_processor):
    created = (
        await client.post(
            "/library/documents",
            data={"title": "SOP One"},
            files={"file": ("sop.pdf", io.BytesIO(_PDF_CONTENT), "application/pdf")},
            headers=auth_headers,
        )
    ).json()
    resp = await client.get("/library/documents/by-slug/sop-one", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_organizations_list_exposes_derived_slug(client, auth_headers):
    resp = await client.get("/iam/organizations", headers=auth_headers)
    assert resp.status_code == 200
    orgs = resp.json()
    assert orgs, "expected the caller to belong to at least one org"
    for org in orgs:
        assert "slug" in org
        assert org["slug"] == org["slug"].lower()


# ─── F-0091 Task 20b: slug exposure on navigation responses ─────────────────


@pytest.mark.asyncio
async def test_project_scoped_protocol_response_exposes_project_slug(
    client, auth_headers
):
    """A project-scoped protocol surfaces its owning project's slug."""
    proj = (
        await client.post(
            "/projects/", json={"name": "CHO Line"}, headers=auth_headers
        )
    ).json()
    resp = await client.post(
        "/protocols",
        json={"name": "Seed Train", "project_id": proj["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["project_slug"] == "cho-line"


@pytest.mark.asyncio
async def test_org_scoped_protocol_response_has_null_project_slug(
    client, auth_headers, test_org
):
    """A library (org-scoped) protocol has no project, so project_slug is null."""
    resp = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["project_slug"] is None


@pytest.mark.asyncio
async def test_dashboard_run_summary_exposes_run_and_project_slug(
    client, auth_headers, test_org
):
    """RunSummary rows in the dashboard carry the run slug + project slug."""
    proj = (
        await client.post(
            "/projects/", json={"name": "CHO Line"}, headers=auth_headers
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={"name": "Seeding Run", "project_id": proj["id"]},
            headers=auth_headers,
        )
    ).json()

    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    planned = resp.json()["my_work"]["planned_runs"]
    summary = next(r for r in planned if r["id"] == run["id"])
    assert summary["slug"] == run["slug"]
    assert summary["project_slug"] == "cho-line"

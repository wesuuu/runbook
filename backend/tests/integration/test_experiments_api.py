import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run

# --- Fixtures ---


@pytest_asyncio.fixture
async def protocol(db_session: AsyncSession, test_project: Project):
    """A protocol in the test project for creating runs."""
    proto = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        graph={"nodes": [], "edges": []},
        slug="test-protocol-exp",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def standalone_run(
    db_session: AsyncSession,
    test_project: Project,
    protocol: Protocol,
):
    """A run not associated with any experiment."""
    run = Run(
        name="Standalone Run",
        project_id=test_project.id,
        protocol_id=protocol.id,
        slug="standalone-run",
        graph=protocol.graph.copy() if protocol.graph else {},
    )
    db_session.add(run)
    await db_session.flush()
    return run


# --- Create Experiment ---


@pytest.mark.asyncio
async def test_create_experiment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/experiments",
        json={
            "name": "MOI Optimization",
            "project_id": str(test_project.id),
            "description": "Testing MOI values 3, 5, 10",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "MOI Optimization"
    assert body["description"] == "Testing MOI values 3, 5, 10"
    assert body["status"] == "DRAFT"
    assert body["project_id"] == str(test_project.id)
    assert body["content"] == {}
    assert body["notes"] == []
    assert body["runs"] == []
    assert body["run_count"] == 0
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_experiment_minimal(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    """Create with only required fields."""
    resp = await client.post(
        "/experiments",
        json={
            "name": "Quick Experiment",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Quick Experiment"
    assert body["description"] is None


# --- List Experiments ---


@pytest.mark.asyncio
async def test_list_experiments_for_project(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    # Create two experiments
    for name in ["Exp A", "Exp B"]:
        await client.post(
            "/experiments",
            json={"name": name, "project_id": str(test_project.id)},
            headers=auth_headers,
        )

    resp = await client.get(
        f"/projects/{test_project.id}/experiments",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # List should include run_count but no nested runs
    for exp in body:
        assert "run_count" in exp
        assert exp["runs"] == []


# --- Get Experiment Detail ---


@pytest.mark.asyncio
async def test_get_experiment_with_runs(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    # Create experiment
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Detail Test",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    # Create a run within the experiment
    await client.post(
        f"/experiments/{exp_id}/runs",
        json={
            "name": "Run 1",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )

    # Get detail
    resp = await client.get(
        f"/experiments/{exp_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_count"] == 1
    assert len(body["runs"]) == 1
    assert body["runs"][0]["name"] == "Run 1"
    assert body["runs"][0]["experiment_id"] == exp_id


# --- Update Experiment ---


@pytest.mark.asyncio
async def test_update_experiment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Original Name",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.put(
        f"/experiments/{exp_id}",
        json={
            "name": "Updated Name",
            "description": "New description",
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Updated Name"
    assert body["description"] == "New description"
    assert body["content"]["type"] == "doc"
    # status is read-only via PUT; remains at its default
    assert body["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_update_experiment_partial(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    """Only update fields that are provided."""
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Keep This Name",
            "project_id": str(test_project.id),
            "description": "Keep this too",
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    # Only update name; description should be preserved as-is
    resp = await client.put(
        f"/experiments/{exp_id}",
        json={"name": "Updated Name Only"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Updated Name Only"
    assert body["description"] == "Keep this too"
    # status is read-only via PUT; remains at its default
    assert body["status"] == "DRAFT"


# --- Archive Experiment (DELETE) ---


@pytest.mark.asyncio
async def test_archive_experiment_cascades_to_runs(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    # Create experiment with a run
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "To Archive",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    run_resp = await client.post(
        f"/experiments/{exp_id}/runs",
        json={
            "name": "Run in Experiment",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = run_resp.json()["id"]

    # Archive
    resp = await client.delete(
        f"/experiments/{exp_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify experiment is archived
    exp_resp = await client.get(
        f"/experiments/{exp_id}",
        headers=auth_headers,
    )
    assert exp_resp.json()["status"] == "ARCHIVED"

    # Verify run is archived too
    run_resp = await client.get(
        f"/runs/{run_id}",
        headers=auth_headers,
    )
    assert run_resp.json()["status"] == "ARCHIVED"


# --- Add Run to Experiment ---


@pytest.mark.asyncio
async def test_create_run_in_experiment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "With Runs",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.post(
        f"/experiments/{exp_id}/runs",
        json={
            "name": "New Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Run"
    assert body["experiment_id"] == exp_id
    assert body["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_link_existing_standalone_run(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    standalone_run: Run,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Link Target",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.post(
        f"/experiments/{exp_id}/runs",
        json={"run_id": str(standalone_run.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["experiment_id"] == exp_id


@pytest.mark.asyncio
async def test_link_run_already_in_experiment_blocked(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    # Create two experiments
    exp1_resp = await client.post(
        "/experiments",
        json={"name": "Exp 1", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp1_id = exp1_resp.json()["id"]

    exp2_resp = await client.post(
        "/experiments",
        json={"name": "Exp 2", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp2_id = exp2_resp.json()["id"]

    # Create a run in exp1
    run_resp = await client.post(
        f"/experiments/{exp1_id}/runs",
        json={
            "name": "Claimed Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = run_resp.json()["id"]

    # Try to link to exp2 — should fail
    resp = await client.post(
        f"/experiments/{exp2_id}/runs",
        json={"run_id": run_id},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# --- Unlink Run ---


@pytest.mark.asyncio
async def test_unlink_run_from_experiment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Unlink Test",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    run_resp = await client.post(
        f"/experiments/{exp_id}/runs",
        json={
            "name": "To Unlink",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = run_resp.json()["id"]

    # Unlink
    resp = await client.delete(
        f"/experiments/{exp_id}/runs/{run_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify run is standalone now
    run_detail = await client.get(
        f"/runs/{run_id}",
        headers=auth_headers,
    )
    assert run_detail.json()["experiment_id"] is None


# --- Notes ---


@pytest.mark.asyncio
async def test_add_and_list_experiment_notes(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Notes Test",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    # Add a note
    note_resp = await client.post(
        f"/experiments/{exp_id}/notes",
        json={"content": "Observed elevated pH in all runs"},
        headers=auth_headers,
    )
    assert note_resp.status_code == 201
    note = note_resp.json()
    assert note["content"] == "Observed elevated pH in all runs"
    assert "id" in note
    assert "author_id" in note
    assert "created_at" in note

    # List notes
    list_resp = await client.get(
        f"/experiments/{exp_id}/notes",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["content"] == "Observed elevated pH in all runs"


@pytest.mark.asyncio
async def test_experiment_note_with_flags(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={
            "name": "Flag Test",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.post(
        f"/experiments/{exp_id}/notes",
        json={
            "content": "Anomalous result",
            "flags": ["observation"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert "observation" in resp.json()["flags"]


# --- Name & description validation ---


@pytest.mark.asyncio
async def test_create_rejects_empty_name(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/experiments",
        json={"name": "", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_whitespace_only_name(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/experiments",
        json={"name": "   \t\n   ", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_overlong_name(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/experiments",
        json={"name": "X" * 201, "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_overlong_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/experiments",
        json={
            "name": "Valid",
            "project_id": str(test_project.id),
            "description": "Y" * 5001,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_rejects_whitespace_only_name(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={"name": "Original", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.put(
        f"/experiments/{exp_id}",
        json={"name": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_rejects_overlong_name(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={"name": "Original", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.put(
        f"/experiments/{exp_id}",
        json={"name": "X" * 201},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# --- Slug stability (C2) ---


@pytest.mark.asyncio
async def test_slug_stable_across_name_changes(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    """Renaming an experiment must not regenerate its slug — URLs/bookmarks
    stay valid (C2)."""
    create_resp = await client.post(
        "/experiments",
        json={"name": "First Name", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]
    original_slug = create_resp.json()["slug"]
    assert original_slug == "first-name"

    put_resp = await client.put(
        f"/experiments/{exp_id}",
        json={"name": "Completely Different Name"},
        headers=auth_headers,
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["slug"] == original_slug

    # Verify slug-based lookup still resolves
    lookup = await client.get(
        f"/experiments/by-slug/{test_project.slug}/{original_slug}",
        headers=auth_headers,
    )
    assert lookup.status_code == 200
    assert lookup.json()["name"] == "Completely Different Name"


# --- DELETE note (C3) ---


@pytest.mark.asyncio
async def test_delete_note_by_author(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    create_resp = await client.post(
        "/experiments",
        json={"name": "Notes Delete", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    add = await client.post(
        f"/experiments/{exp_id}/notes",
        json={"content": "to be deleted"},
        headers=auth_headers,
    )
    note_id = add.json()["id"]

    delete = await client.delete(
        f"/experiments/{exp_id}/notes/{note_id}",
        headers=auth_headers,
    )
    assert delete.status_code == 204

    after = await client.get(
        f"/experiments/{exp_id}/notes", headers=auth_headers
    )
    assert after.json()["items"] == []


@pytest.mark.asyncio
async def test_delete_note_404_when_not_found(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    import uuid

    create_resp = await client.post(
        "/experiments",
        json={"name": "Empty notes", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/experiments/{exp_id}/notes/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_note_non_author_forbidden(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    test_user: User,
):
    """Non-author with EDIT permission cannot delete someone else's note."""
    import uuid as _uuid

    create_resp = await client.post(
        "/experiments",
        json={"name": "Author guard", "project_id": str(test_project.id)},
        headers=auth_headers,
    )
    exp_id = create_resp.json()["id"]

    # Add a note authored by test_user
    add = await client.post(
        f"/experiments/{exp_id}/notes",
        json={"content": "owner's note"},
        headers=auth_headers,
    )
    note_id = add.json()["id"]

    # Rewrite the note's author_id in JSONB to simulate a different author
    from sqlalchemy import select

    from app.models.runs import Experiment

    exp = (
        await db_session.execute(
            select(Experiment).where(Experiment.id == _uuid.UUID(exp_id))
        )
    ).scalar_one()
    notes = list(exp.notes or [])
    notes[0] = {**notes[0], "author_id": str(_uuid.uuid4())}
    exp.notes = notes
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(exp, "notes")
    await db_session.commit()

    resp = await client.delete(
        f"/experiments/{exp_id}/notes/{note_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 403


# --- Permission Check ---


@pytest.mark.asyncio
async def test_create_experiment_without_permission_fails(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
):
    """User from a different org cannot create experiments in this project."""
    resp = await client.post(
        "/experiments",
        json={
            "name": "Should Fail",
            "project_id": str(test_project.id),
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403

"""F-0093 §1.6 — POST /runs must validate experiment_id."""

import pytest

from app.models.projects import Project
from app.models.runs import Experiment, Run


async def _experiment(db, project_id, name, slug, status="DRAFT"):
    exp = Experiment(name=name, slug=slug, project_id=project_id, status=status)
    db.add(exp)
    await db.flush()
    return exp


@pytest.mark.asyncio
async def test_rejects_experiment_in_other_project(
    client, auth_headers, db_session, test_org, test_project,
):
    other = Project(
        name="Other", organization_id=test_org.id, slug="other-p",
        owner_type="USER",
    )
    db_session.add(other)
    await db_session.flush()
    exp = await _experiment(db_session, other.id, "Foreign", "foreign")
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Bad run",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RUN_EXPERIMENT_PROJECT_MISMATCH"


@pytest.mark.asyncio
async def test_rejects_archived_experiment(
    client, auth_headers, db_session, test_project,
):
    exp = await _experiment(
        db_session, test_project.id, "Closed", "closed", status="ARCHIVED"
    )
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Run on archived",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RUN_EXPERIMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_allows_same_project_experiment(
    client, auth_headers, db_session, test_project,
):
    exp = await _experiment(db_session, test_project.id, "Good", "good")
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Valid run",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["experiment_id"] == str(exp.id)


@pytest.mark.asyncio
async def test_rejects_nonexistent_experiment(
    client, auth_headers, test_project,
):
    """A run pointing at a non-existent experiment_id 404s via get_or_404."""
    import uuid

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Run on ghost",
            "project_id": str(test_project.id),
            "experiment_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


# --- POST /experiments/{id}/runs ARCHIVED guard (H2) ---


@pytest.mark.asyncio
async def test_add_run_to_archived_experiment_link_branch_rejected(
    client, auth_headers, db_session, test_project,
):
    """Linking an existing run to an archived experiment is 409."""
    exp = await _experiment(
        db_session, test_project.id, "Closed", "closed-link", status="ARCHIVED"
    )
    run = Run(
        name="Loose run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        slug="loose-run",
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.post(
        f"/experiments/{exp.id}/runs",
        headers=auth_headers,
        json={"run_id": str(run.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "EXPERIMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_add_run_to_archived_experiment_create_branch_rejected(
    client, auth_headers, db_session, test_project,
):
    """Creating a new run inside an archived experiment is 409."""
    exp = await _experiment(
        db_session, test_project.id, "Closed", "closed-create", status="ARCHIVED"
    )
    await db_session.commit()

    resp = await client.post(
        f"/experiments/{exp.id}/runs",
        headers=auth_headers,
        json={"name": "Should not exist"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "EXPERIMENT_ARCHIVED"

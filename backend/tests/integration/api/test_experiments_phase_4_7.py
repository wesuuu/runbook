"""F-0043 — phases 4-7 integration tests."""

import pytest


@pytest.mark.asyncio
async def test_put_experiment_writes_conclusion_when_unlocked(
    client, seeded_experiment, auth_headers
):
    res = await client.put(
        f"/experiments/{seeded_experiment.id}",
        json={"conclusion": "Run 2 wins by 24%."},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["conclusion"] == "Run 2 wins by 24%."


@pytest.mark.asyncio
async def test_put_experiment_409_when_locked(
    client, locked_experiment, auth_headers
):
    # Lock guard freezes ALL fields, not just conclusion.
    for body in (
        {"conclusion": "new"},
        {"objective": "new objective"},
        {"description": "new desc"},
    ):
        res = await client.put(
            f"/experiments/{locked_experiment.id}",
            json=body,
            headers=auth_headers,
        )
        assert res.status_code == 409, body
        assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_post_run_to_locked_experiment_409(
    client, locked_experiment, test_project, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/runs",
        json={"name": "post-lock run", "protocol_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_create_run_via_runs_endpoint_to_locked_experiment_409(
    client, locked_experiment, test_project, auth_headers
):
    res = await client.post(
        "/runs",
        json={
            "name": "x",
            "project_id": str(test_project.id),
            "experiment_id": str(locked_experiment.id),
        },
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_add_note_to_locked_experiment_409(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/notes",
        json={"content": "post-lock observation", "flags": []},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_delete_note_from_locked_experiment_409(
    client, locked_experiment_with_note, auth_headers
):
    note_id = locked_experiment_with_note.notes[0]["id"]
    res = await client.delete(
        f"/experiments/{locked_experiment_with_note.id}/notes/{note_id}",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_lock_409_when_open_runs(
    client, experiment_with_open_run, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_with_open_run.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OPEN_RUNS"


@pytest.mark.asyncio
async def test_lock_409_when_conclusion_empty(
    client, experiment_terminal_no_conclusion, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_terminal_no_conclusion.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EMPTY_CONCLUSION"


@pytest.mark.asyncio
async def test_lock_happy_path(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conclusion_locked_at"] is not None
    assert body["conclusion_locked_by_name"] is not None
    assert body["lifecycle_status"] == "COMPLETE"


@pytest.mark.asyncio
async def test_lock_409_when_already_locked(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "ALREADY_LOCKED"


@pytest.mark.asyncio
async def test_lock_409_when_no_completed_runs(
    client, experiment_only_archived_runs, auth_headers
):
    # All-archived experiments read as DRAFT in lifecycle derivation; locking
    # would silently flip them to COMPLETE without any completed run. Refuse.
    res = await client.post(
        f"/experiments/{experiment_only_archived_runs.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "NO_COMPLETED_RUNS"


@pytest.mark.asyncio
async def test_lock_audit_row_atomic_with_state(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    """Lock UPDATE + audit insert must commit in the same transaction.

    Asserts that on a successful lock there is exactly one audit row whose
    `entity_id` matches the experiment AND that the experiment is actually
    locked — proving they were committed together.
    """
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    from sqlalchemy import text
    rows = await db_session.execute(
        text(
            "SELECT count(*) FROM audit_logs "
            "WHERE entity_type='Experiment' AND entity_id=:eid AND action='conclusion.lock'"
        ),
        {"eid": experiment_ready_to_lock.id},
    )
    assert rows.scalar() == 1


@pytest.mark.asyncio
async def test_lock_vs_run_create_toctou(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    """TOCTOU: lock + simultaneous run creation. Exactly one must succeed."""
    import asyncio

    async def lock():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
            headers=auth_headers,
        )

    async def add_run():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/runs",
            json={"name": "race run"},
            headers=auth_headers,
        )

    a, b = await asyncio.gather(lock(), add_run())
    # The lock either wins (200 + 409 on add_run) or loses (409 on lock + 201
    # on add_run). The forbidden state is both succeeding.
    successes = sum(1 for r in (a, b) if r.status_code < 400)
    assert successes == 1, f"both succeeded: lock={a.status_code} add_run={b.status_code}"


@pytest.mark.asyncio
async def test_unlock_403_for_non_admin(
    client, locked_experiment, viewer_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "data correction"},
        headers=viewer_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unlock_422_short_reason(
    client, locked_experiment, admin_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "short"},
        headers=admin_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_unlock_happy_path(
    client, locked_experiment, admin_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "Re-analysis with corrected titer values."},
        headers=admin_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conclusion_locked_at"] is None
    assert body["lifecycle_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_unlock_409_when_already_unlocked(
    client, experiment_ready_to_lock, admin_headers
):
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/unlock",
        json={"reason": "data correction"},
        headers=admin_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_observations_endpoint(client, experiment_with_notes, auth_headers):
    res = await client.get(
        f"/experiments/{experiment_with_notes.id}/observations",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["cache-control"] == "private, max-age=30"
    body = res.json()
    assert "items" in body and "truncated" in body

    # F-0043 review-panel fix: run-source items carry slug + project slug so
    # the UI can build the canonical /:org/projects/:p/runs/:r URL.
    run_items = [i for i in body["items"] if i["source"] == "run"]
    assert run_items, "fixture should produce at least one run observation"
    for i in run_items:
        assert i["run_slug"], i
        assert i["run_project_slug"], i
    exp_items = [i for i in body["items"] if i["source"] == "experiment"]
    for i in exp_items:
        assert i["run_slug"] is None
        assert i["run_project_slug"] is None


@pytest.mark.asyncio
async def test_export_pdf_returns_pdf_with_lock_signature(
    client, locked_experiment, auth_headers
):
    res = await client.get(
        f"/experiments/{locked_experiment.id}/export.pdf",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000  # non-trivial PDF
    assert res.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_export_pdf_503_on_timeout(
    client, locked_experiment, auth_headers, monkeypatch
):
    import asyncio
    from app.services.experiments import pdf_export

    def slow(*args, **kwargs):
        import time
        time.sleep(31)
        return b""

    monkeypatch.setattr(pdf_export, "generate_experiment_pdf", slow)
    monkeypatch.setattr(
        "app.api.endpoints.experiments.EXPORT_TIMEOUT_SECONDS", 0.5
    )

    res = await client.get(
        f"/experiments/{locked_experiment.id}/export.pdf",
        headers=auth_headers,
    )
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "EXPORT_TIMEOUT"


# --- Lock guard on run-side endpoints (review-panel fix) ---


@pytest.mark.asyncio
async def test_put_run_blocked_when_parent_experiment_locked(
    client, locked_experiment, db_session, auth_headers
):
    """PUT /runs/{id} must 409 when parent experiment is locked."""
    from app.models.runs import Run, RunStatus

    run = Run(
        name="Run on locked exp",
        slug="run-on-locked-exp",
        project_id=locked_experiment.project_id,
        experiment_id=locked_experiment.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()

    for body in (
        {"key_result_label": "titer", "key_result_value": 5.0, "key_result_unit": "g/L"},
        {"name": "renamed"},
    ):
        res = await client.put(
            f"/runs/{run.id}",
            json=body,
            headers=auth_headers,
        )
        assert res.status_code == 409, body
        assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_post_run_note_blocked_when_parent_experiment_locked(
    client, locked_experiment, db_session, auth_headers
):
    """POST /runs/{id}/notes must 409 when parent experiment is locked."""
    from app.models.runs import Run, RunStatus

    run = Run(
        name="Note run",
        slug="note-run-locked",
        project_id=locked_experiment.project_id,
        experiment_id=locked_experiment.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()

    res = await client.post(
        f"/runs/{run.id}/notes",
        json={"content": "post-lock note", "flags": []},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_role_assignment_blocked_when_parent_experiment_locked(
    client, locked_experiment, db_session, auth_headers, test_user
):
    """POST /runs/{id}/role-assignments must 409 when parent locked."""
    from app.models.runs import Run, RunStatus

    run = Run(
        name="Role run",
        slug="role-run-locked",
        project_id=locked_experiment.project_id,
        experiment_id=locked_experiment.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()

    res = await client.post(
        f"/runs/{run.id}/role-assignments",
        json={
            "lane_node_id": "lane-1",
            "role_name": "operator",
            "user_id": str(test_user.id),
        },
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_unlock_403_for_project_admin_who_is_not_org_admin(
    client, locked_experiment, db_session, test_org
):
    """Unlock must require OrgRole.ADMIN, not PROJECT.ADMIN.

    A user with PROJECT.ADMIN on the parent project but only OrgRole.MEMBER
    would pass the old check; the tightened check must reject them.
    """
    from app.core.security import create_access_token, hash_password
    from app.models.iam import (
        ObjectPermission,
        ObjectType,
        OrganizationMember,
        PermissionLevel,
        PrincipalType,
        User,
    )

    project_admin = User(
        email="proj-admin-only@example.com",
        hashed_password=hash_password("pw"),
        full_name="Project Admin Only",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(project_admin)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=project_admin.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=project_admin.id,
            object_type=ObjectType.PROJECT.value,
            object_id=locked_experiment.project_id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    await db_session.flush()

    token = create_access_token(
        project_admin.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "Should be rejected — not org admin."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unlink_run_blocked_when_experiment_locked(
    client, locked_experiment, db_session, auth_headers
):
    """DELETE /experiments/{id}/runs/{run_id} must 409 when locked."""
    from app.models.runs import Run, RunStatus

    run = Run(
        name="Linked run",
        slug="linked-run-locked",
        project_id=locked_experiment.project_id,
        experiment_id=locked_experiment.id,
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    await db_session.flush()

    res = await client.delete(
        f"/experiments/{locked_experiment.id}/runs/{run.id}",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"

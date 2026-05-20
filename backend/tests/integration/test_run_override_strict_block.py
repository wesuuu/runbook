"""Integration tests for the override-block on strict runs (F-0066, Task 13).

Once Run.is_strict is True (snapshotted from a designated protocol), the
endpoint must reject any incoming overrides — both at run-creation time
(POST /runs with `overrides`) and during edits to the run's graph
(PUT /runs/{run_id} with a `graph` diff that touches a unit op).
"""

import copy
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run


def _minimal_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Step 1",
                    "params": {"pH": 7.0, "temp_c": 25},
                    "paramSchema": {
                        "properties": {
                            "pH": {"type": "number", "title": "pH"},
                            "temp_c": {"type": "number", "title": "Temperature"},
                        }
                    },
                },
            }
        ],
        "edges": [],
    }


async def _make_protocol(
    db: AsyncSession,
    project: Project,
    *,
    requires_approval: bool,
    status: str = "APPROVED",
) -> Protocol:
    _hex = uuid.uuid4().hex[:6]
    p = Protocol(
        name=f"P-{_hex}",
        project_id=project.id,
        status=status,
        requires_approval=requires_approval,
        version_number=1,
        graph=_minimal_graph(),
        slug=f"p-{_hex}",
        owner_org_id=project.organization_id,
    )
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_create_run_overrides_blocked_when_strict(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """APPROVED designated protocol + overrides payload → 403 RUN_IS_STRICT."""
    proto = await _make_protocol(db_session, test_project, requires_approval=True)
    resp = await client.post(
        "/runs",
        json={
            "name": "Strict run with overrides",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
            "overrides": {"nodes": {"n1": {"params": {"pH": 6.5}}}},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "RUN_IS_STRICT"
    else:
        assert "RUN_IS_STRICT" in resp.text


@pytest.mark.asyncio
async def test_create_run_overrides_ok_when_not_strict(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Non-designated protocol + overrides → 201 succeeds."""
    proto = await _make_protocol(
        db_session, test_project, requires_approval=False, status="DRAFT"
    )
    resp = await client.post(
        "/runs",
        json={
            "name": "Loose run with overrides",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
            "overrides": {"nodes": {"n1": {"params": {"pH": 6.5}}}},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_strict"] is False


@pytest.mark.asyncio
async def test_update_run_override_edit_blocked_when_strict(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """A strict run rejects PUT /runs/{id} when graph has unit-op param diffs."""
    proto = await _make_protocol(db_session, test_project, requires_approval=True)
    # Create the strict run via endpoint to ensure is_strict is set the same
    # way the production code path does.
    create_resp = await client.post(
        "/runs",
        json={
            "name": "Strict run",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    run_id = create_resp.json()["id"]
    assert create_resp.json()["is_strict"] is True

    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    new_graph = copy.deepcopy(run.graph)
    # Mutate a unit-op param so diff_unit_op_node yields an OVERRIDE_EDIT.
    for node in new_graph["nodes"]:
        if node["id"] == "n1":
            node["data"]["params"]["pH"] = 6.0
            break

    resp = await client.put(
        f"/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "RUN_IS_STRICT"
    else:
        assert "RUN_IS_STRICT" in resp.text


@pytest.mark.asyncio
async def test_update_run_override_edit_ok_when_not_strict(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """A non-strict run still accepts graph mutations on PLANNED."""
    proto = await _make_protocol(
        db_session, test_project, requires_approval=False, status="DRAFT"
    )
    create_resp = await client.post(
        "/runs",
        json={
            "name": "Loose run",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    run_id = create_resp.json()["id"]
    assert create_resp.json()["is_strict"] is False

    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    new_graph = copy.deepcopy(run.graph)
    for node in new_graph["nodes"]:
        if node["id"] == "n1":
            node["data"]["params"]["pH"] = 6.0
            break

    resp = await client.put(
        f"/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

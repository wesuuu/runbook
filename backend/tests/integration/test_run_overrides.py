"""Integration tests for run override behavior on POST/PUT /runs.

These exercise the full HTTP path so the service-layer helpers and the
endpoint plumbing are tested together.
"""

import copy

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AuditLog
from app.models.projects import Project
from app.models.protocols import Protocol, ProtocolVersion
from app.models.runs import Run


def _sample_protocol_graph() -> dict:
    """A minimal but realistic protocol graph: two unit-op nodes."""
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Buffer Mix",
                    "params": {"pH": 7.4, "temp_c": 25},
                    "equipment": [{"id": "eq-A", "name": "Bioreactor A"}],
                    "paramSchema": {
                        "properties": {
                            "pH": {"type": "number", "title": "Target pH"},
                            "temp_c": {"type": "number", "title": "Temperature"},
                        }
                    },
                    "description": "Mix until pH={{pH}}",
                },
            },
            {
                "id": "n2",
                "type": "unitOp",
                "data": {
                    "label": "Centrifugation",
                    "params": {"rpm": 4000},
                    "equipment": [{"id": "cf-A", "name": "Centrifuge A"}],
                    "paramSchema": {
                        "properties": {"rpm": {"type": "number", "title": "Spin speed"}}
                    },
                    "description": "Spin at {{rpm}} rpm",
                },
            },
        ],
        "edges": [],
    }


async def _seed_protocol(
    db_session: AsyncSession,
    project: Project,
    graph: dict | None = None,
) -> Protocol:
    p = Protocol(
        name="Test Protocol",
        project_id=project.id,
        status="APPROVED",
        version_number=1,
        graph=graph or _sample_protocol_graph(),
        slug="test-protocol",
        owner_org_id=project.organization_id,
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_create_run_no_overrides_populates_mirror_fields(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """With no overrides, every unit-op node still gets its protocol_* mirror
    fields populated, and Run.graph is a deep copy of Protocol.graph."""
    protocol = await _seed_protocol(db_session, test_project)
    original_graph = copy.deepcopy(protocol.graph)

    resp = await client.post(
        "/runs",
        json={
            "name": "Run 1",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Reload run + protocol
    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    nodes = run.graph["nodes"]
    n1 = next(n for n in nodes if n["id"] == "n1")

    # Mirror fields populated
    assert n1["data"]["protocol_params"] == {"pH": 7.4, "temp_c": 25}
    assert n1["data"]["protocol_equipment"] == [{"id": "eq-A", "name": "Bioreactor A"}]
    assert n1["data"]["protocol_description"] == "Mix until pH={{pH}}"
    # Effective values unchanged
    assert n1["data"]["params"] == {"pH": 7.4, "temp_c": 25}

    # Deep-copy regression: mutating run.graph does NOT mutate protocol.graph
    n1["data"]["params"]["pH"] = 999
    await db_session.flush()
    fresh_protocol = (
        await db_session.execute(select(Protocol).where(Protocol.id == protocol.id))
    ).scalar_one()
    assert (
        fresh_protocol.graph == original_graph
    ), "Mutating Run.graph leaked into Protocol.graph — likely a shallow copy bug"


@pytest.mark.asyncio
async def test_create_run_sparse_value_overrides(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Sparse override merges with defaults; mirrors preserve originals; one
    OVERRIDE_SET audit entry per overridden field."""
    protocol = await _seed_protocol(db_session, test_project)

    resp = await client.post(
        "/runs",
        json={
            "name": "Run pH",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {
                    "n1": {"params": {"pH": 6.8}},
                }
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert n1["data"]["params"] == {"pH": 6.8, "temp_c": 25}
    assert n1["data"]["protocol_params"] == {"pH": 7.4, "temp_c": 25}

    # Audit: one OVERRIDE_SET entry for pH
    audit_q = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "Run")
            & (AuditLog.entity_id == run.id)
            & (AuditLog.action == "OVERRIDE_SET")
        )
    )
    entries = audit_q.scalars().all()
    assert len(entries) == 1
    assert entries[0].changes["step_id"] == "n1"
    assert entries[0].changes["field"] == "pH"
    assert entries[0].changes["field_label"] == "Target pH"
    assert entries[0].changes["old_value"] == 7.4
    assert entries[0].changes["new_value"] == 6.8


@pytest.mark.asyncio
async def test_create_run_equipment_swap(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    resp = await client.post(
        "/runs",
        json={
            "name": "Run swap",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {
                    "n2": {"equipment": [{"id": "cf-B", "name": "Centrifuge B"}]},
                }
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (
        await db_session.execute(select(Run).where(Run.id == resp.json()["id"]))
    ).scalar_one()
    n2 = next(n for n in run.graph["nodes"] if n["id"] == "n2")
    assert n2["data"]["equipment"] == [{"id": "cf-B", "name": "Centrifuge B"}]
    assert n2["data"]["protocol_equipment"] == [{"id": "cf-A", "name": "Centrifuge A"}]


@pytest.mark.asyncio
async def test_create_run_paramSchema_override(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Replacing paramSchema (e.g. wizard added a new param row) is stored as
    a full schema replacement; mirror keeps original."""
    protocol = await _seed_protocol(db_session, test_project)
    new_schema = {
        "properties": {
            "pH": {"type": "number", "title": "Target pH"},
            "temp_c": {"type": "number", "title": "Temperature"},
            "buffer_lot": {"type": "string", "title": "Buffer lot"},
        }
    }
    resp = await client.post(
        "/runs",
        json={
            "name": "Run schema",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {"n1": {"paramSchema": new_schema}},
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (
        await db_session.execute(select(Run).where(Run.id == resp.json()["id"]))
    ).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert "buffer_lot" in n1["data"]["paramSchema"]["properties"]
    assert "buffer_lot" not in n1["data"]["protocol_paramSchema"]["properties"]


@pytest.mark.asyncio
async def test_create_run_description_override(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    new_desc = "Adjust to {{pH}} using 1M HCl, then incubate at {{temp_c}}°C"
    resp = await client.post(
        "/runs",
        json={
            "name": "Run desc",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {"n1": {"description": new_desc}},
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (
        await db_session.execute(select(Run).where(Run.id == resp.json()["id"]))
    ).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert n1["data"]["description"] == new_desc
    assert n1["data"]["protocol_description"] == "Mix until pH={{pH}}"


@pytest.mark.asyncio
async def test_create_run_from_specific_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """When protocol_version_number is set, the run snapshots that
    ProtocolVersion.graph, not protocol.graph."""
    protocol = await _seed_protocol(db_session, test_project)

    # Create an older published version with a different graph
    old_graph = {
        "nodes": [
            {
                "id": "old-n1",
                "type": "unitOp",
                "data": {
                    "label": "Legacy step",
                    "params": {"x": 1},
                    "paramSchema": {"properties": {"x": {"type": "integer"}}},
                },
            }
        ],
        "edges": [],
    }
    db_session.add(
        ProtocolVersion(
            protocol_id=protocol.id,
            version_number=1,
            name=protocol.name,
            graph=old_graph,
            is_draft=False,
        )
    )
    # Bump the protocol's current version to 2 so v1 is "old"
    protocol.version_number = 2
    await db_session.flush()

    resp = await client.post(
        "/runs",
        json={
            "name": "Run from v1",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "protocol_version_number": 1,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (
        await db_session.execute(select(Run).where(Run.id == resp.json()["id"]))
    ).scalar_one()
    node_ids = {n["id"] for n in run.graph["nodes"]}
    assert node_ids == {"old-n1"}  # snapshotted v1, not the current protocol graph


@pytest.mark.asyncio
async def test_create_run_with_unknown_version_returns_404(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    resp = await client.post(
        "/runs",
        json={
            "name": "Run from missing version",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "protocol_version_number": 99,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_run_graph_allowed_while_planned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # PLANNED is the default — confirm the guard does NOT trigger.
    new_graph = copy.deepcopy(create_resp.json()["graph"])
    n1 = next(n for n in new_graph["nodes"] if n["id"] == "n1")
    n1["data"]["params"]["pH"] = 6.8

    resp = await client.put(
        f"/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    n1_resp = next(n for n in resp.json()["graph"]["nodes"] if n["id"] == "n1")
    assert n1_resp["data"]["params"]["pH"] == 6.8


@pytest.mark.asyncio
async def test_update_run_graph_rejected_when_not_planned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user,
    db_session: AsyncSession,
):
    """Once a run leaves PLANNED, graph edits return 422."""
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # Mark ACTIVE directly in the DB to skip the role-assignment guard, which
    # is unrelated to the override behavior under test.
    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    run.status = "ACTIVE"
    await db_session.flush()

    new_graph = copy.deepcopy(create_resp.json()["graph"])
    n1 = next(n for n in new_graph["nodes"] if n["id"] == "n1")
    n1["data"]["params"]["pH"] = 6.8

    resp = await client.put(
        f"/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "PLANNED" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_run_emits_override_edit_audit(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Editing override values on a PLANNED run writes one OVERRIDE_EDIT
    entry per changed (node, field) tuple."""
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {"nodes": {"n1": {"params": {"pH": 6.8}}}},
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # Flip pH to a third value and swap n2's equipment.
    new_graph = copy.deepcopy(create_resp.json()["graph"])
    n1 = next(n for n in new_graph["nodes"] if n["id"] == "n1")
    n2 = next(n for n in new_graph["nodes"] if n["id"] == "n2")
    n1["data"]["params"]["pH"] = 7.0
    n2["data"]["equipment"] = [{"id": "cf-B", "name": "Centrifuge B"}]

    resp = await client.put(
        f"/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    audit_q = await db_session.execute(
        select(AuditLog)
        .where(
            (AuditLog.entity_type == "Run")
            & (AuditLog.entity_id == run_id)
            & (AuditLog.action == "OVERRIDE_EDIT")
        )
        .order_by(AuditLog.created_at)
    )
    entries = audit_q.scalars().all()
    fields = sorted((e.changes["step_id"], e.changes["field"]) for e in entries)
    assert fields == [("n1", "pH"), ("n2", "equipment")]

    # pH entry: old_value should be the previous override (6.8), not the
    # protocol default (7.4) — this is the edit-time semantic.
    ph_entry = next(e for e in entries if e.changes["field"] == "pH")
    assert ph_entry.changes["old_value"] == 6.8
    assert ph_entry.changes["new_value"] == 7.0

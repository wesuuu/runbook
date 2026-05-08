"""Integration tests for QA-0006 branch-role rule enforcement.

Verifies that publish-draft, /runs creation, and PDF endpoints all reject
graphs where a branching unit-op fans out to two targets sharing the same
parentId (or without any parentId), returning 400 with the
branch_requires_distinct_roles error code.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Project, Protocol


def _branching_invalid_graph() -> dict:
    """Minimal graph that triggers branch_requires_distinct_roles.

    Topology: ps -> a -> b, b -> c and b -> d where c and d both have
    parentId 'lane-A'.  b is a unitOp that fans out to c and d which share
    the same lane/role — the rule must fire.
    """
    return {
        "nodes": [
            {
                "id": "ps",
                "type": "processStart",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Start"},
            },
            {
                "id": "lane-A",
                "type": "swimLane",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Lane A"},
            },
            {
                "id": "a",
                "type": "unitOp",
                "parentId": "lane-A",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "A",
                    "category": "Media Prep",
                    "description": "step a",
                    "duration_min": 30,
                    "paramSchema": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                    },
                },
            },
            {
                "id": "b",
                "type": "unitOp",
                "parentId": "lane-A",
                "position": {"x": 100, "y": 0},
                "data": {
                    "label": "B",
                    "category": "Media Prep",
                    "description": "step b",
                    "duration_min": 30,
                    "paramSchema": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                    },
                },
            },
            {
                "id": "c",
                "type": "unitOp",
                "parentId": "lane-A",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "C",
                    "category": "Media Prep",
                    "description": "step c",
                    "duration_min": 30,
                    "paramSchema": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                    },
                },
            },
            {
                "id": "d",
                "type": "unitOp",
                "parentId": "lane-A",
                "position": {"x": 250, "y": 0},
                "data": {
                    "label": "D",
                    "category": "Media Prep",
                    "description": "step d",
                    "duration_min": 30,
                    "paramSchema": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                    },
                },
            },
        ],
        "edges": [
            {"id": "e0", "source": "ps", "target": "a"},
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c"},
            {"id": "e3", "source": "b", "target": "d"},
        ],
        "timeEnabled": False,
        "pixelsPerHour": 200,
        "layout": "horizontal",
    }


def _assert_branch_role_error(resp) -> None:
    """Assert the response is 400 with branch_requires_distinct_roles detail."""
    assert resp.status_code == 400, (
        f"Expected 400, got {resp.status_code}. Body: {resp.text}"
    )
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "branch_requires_distinct_roles", (
        f"Expected error='branch_requires_distinct_roles', got: {detail}"
    )


async def _create_protocol_with_draft(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    project: Project,
    graph: dict,
) -> Protocol:
    """Create a Protocol directly in the DB, then save a draft via the API.

    Returns the Protocol ORM instance.
    """
    protocol = Protocol(
        name="QA-0006 Test Protocol",
        project_id=project.id,
        status="DRAFT",
        version_number=0,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save the graph as a draft version (creates ProtocolVersion is_draft=True)
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"save_as_draft failed: {resp.text}"

    return protocol


# ---------------------------------------------------------------------------
# Test 1: publish-draft rejects invalid branching graph
# ---------------------------------------------------------------------------


async def test_publish_draft_rejects_invalid_branching_graph(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """POST /science/protocols/{id}/publish-draft should 400 on branch error."""
    graph = _branching_invalid_graph()
    protocol = await _create_protocol_with_draft(
        client, auth_headers, db_session, test_project, graph
    )

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    _assert_branch_role_error(resp)


# ---------------------------------------------------------------------------
# Test 2: create run rejects invalid branching protocol graph
# ---------------------------------------------------------------------------


async def test_create_run_rejects_invalid_branching_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """POST /science/runs should 400 when protocol graph violates branch rule."""
    # Store the invalid graph directly on the Protocol so runs picks it up.
    protocol = Protocol(
        name="QA-0006 Run Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph=_branching_invalid_graph(),
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.post(
        "/science/runs",
        json={
            "name": "QA-0006 Test Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    _assert_branch_role_error(resp)


# ---------------------------------------------------------------------------
# Test 3: GET SOP PDF rejects invalid branching protocol graph
# ---------------------------------------------------------------------------


async def test_pdf_sop_get_rejects_invalid_branching_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """GET /science/protocols/{id}/pdf/sop should 400 on branch error."""
    protocol = Protocol(
        name="QA-0006 SOP PDF Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph=_branching_invalid_graph(),
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}/pdf/sop",
        headers=auth_headers,
    )
    _assert_branch_role_error(resp)


# ---------------------------------------------------------------------------
# Test 4: POST batch-record PDF preview rejects invalid graph payload
# ---------------------------------------------------------------------------


async def test_pdf_batch_record_post_rejects_invalid_branching_payload(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """POST /science/protocols/{id}/pdf/batch-record should 400 on branch error."""
    # The POST endpoint validates body.graph, not protocol.graph.
    # The protocol still needs to exist and be accessible.
    protocol = Protocol(
        name="QA-0006 Batch Record Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.post(
        f"/science/protocols/{protocol.id}/pdf/batch-record",
        json={"graph": _branching_invalid_graph()},
        headers=auth_headers,
    )
    _assert_branch_role_error(resp)

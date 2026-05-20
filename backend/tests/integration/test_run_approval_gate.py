"""Integration tests for the run-creation approval gate (F-0066, Task 12).

When a project has require_protocol_approval=True AND the protocol opts into
the approval workflow (requires_approval=True), runs may not be created from
the protocol unless its status is APPROVED.

Independent of the project setting, once a protocol opts in, every run
spawned from it must be marked Run.is_strict=True at creation time.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import Project
from app.models.protocols import Protocol


def _minimal_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Step 1",
                    "params": {"pH": 7.0},
                    "paramSchema": {
                        "properties": {"pH": {"type": "number", "title": "pH"}}
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
    status: str = "DRAFT",
    requires_approval: bool = True,
) -> Protocol:
    p = Protocol(
        name=f"P-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=status,
        requires_approval=requires_approval,
        version_number=1,
        graph=_minimal_graph(),
    )
    db.add(p)
    await db.flush()
    return p


async def _set_project_setting_on(db: AsyncSession, project: Project) -> None:
    project.settings = {
        **(project.settings or {}),
        "require_protocol_approval": True,
    }
    await db.flush()


@pytest.mark.asyncio
async def test_run_create_blocked_when_protocol_not_approved(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """DRAFT designated protocol + project setting on → 400 PROTOCOL_NOT_APPROVED."""
    await _set_project_setting_on(db_session, test_project)
    proto = await _make_protocol(
        db_session, test_project, status="DRAFT", requires_approval=True
    )
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run blocked",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # detail may be a dict (structured error) or contain the keyword
    assert "approved" in resp.text.lower()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "PROTOCOL_NOT_APPROVED"


@pytest.mark.asyncio
async def test_run_create_snapshots_is_strict_from_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """APPROVED designated protocol → 201, response shows is_strict=true."""
    await _set_project_setting_on(db_session, test_project)
    proto = await _make_protocol(
        db_session, test_project, status="APPROVED", requires_approval=True
    )
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run strict",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_strict"] is True


@pytest.mark.asyncio
async def test_run_create_allowed_when_setting_off(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """DRAFT designated protocol + setting OFF → succeeds; is_strict=true
    because the protocol itself opts in."""
    # No project setting tweak; default has no require_protocol_approval.
    proto = await _make_protocol(
        db_session, test_project, status="DRAFT", requires_approval=True
    )
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run setting off",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # Independent of project setting: protocol-level opt-in flips is_strict.
    assert resp.json()["is_strict"] is True


@pytest.mark.asyncio
async def test_run_create_allowed_when_protocol_not_designated(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """DRAFT non-designated protocol + setting on → succeeds, is_strict=false."""
    await _set_project_setting_on(db_session, test_project)
    proto = await _make_protocol(
        db_session, test_project, status="DRAFT", requires_approval=False
    )
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run not designated",
            "project_id": str(test_project.id),
            "protocol_id": str(proto.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_strict"] is False

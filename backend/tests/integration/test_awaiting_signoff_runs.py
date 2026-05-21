"""Tests for list_runs_awaiting_signoff_for_user (F-0092)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.protocols import Protocol
from app.models.runs import Run, RunRoleAssignment
from app.models.signoffs import GlpSignoff
from app.models.projects import Project
from app.services.runs.graph_facts import extract_graph_facts
from app.services.signoffs.queries import list_runs_awaiting_signoff_for_user

_GRAPH = {"nodes": [{"id": "op-1", "type": "unitOp"}]}


async def _glp_protocol(db, project, *, enabled=True, qau=False):
    proto = Protocol(
        name="P",
        project_id=project.id,
        status="APPROVED",
        graph={"glpSettings": {"glp_enabled": enabled, "require_qau": qau}},
    )
    db.add(proto)
    await db.flush()
    return proto


async def _run(db, project, proto, user, *, status="ACTIVE", completed=True):
    run = Run(
        name="R",
        project_id=project.id,
        protocol_id=proto.id,
        status=status,
        graph=_GRAPH,
        execution_data={"op-1": {"status": "completed" if completed else "x"}},
        started_by_id=user.id,
    )
    db.add(run)
    await db.flush()
    return run


def _facts(runs):
    return {r.id: extract_graph_facts(r.graph or {}) for r in runs}


def _approved_signoff(run_id, role: str, signer_id):
    """A valid APPROVED run sign-off.

    ``GlpSignoff.signed_at`` is NOT NULL, and the ``ck_approved_requires_attestation``
    CHECK constraint requires ``attestation`` + ``signature_image_path`` whenever
    ``action='APPROVED'`` — a bare constructor fails with an IntegrityError.
    """
    return GlpSignoff(
        run_id=run_id,
        role=role,
        action="APPROVED",
        signer_id=signer_id,
        signed_at=datetime.now(timezone.utc),
        attestation="Reviewed and approved.",
        signature_image_path="signatures/test.png",
    )


@pytest.mark.asyncio
async def test_involved_complete_missing_role_qualifies(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project)
    run = await _run(db_session, test_project, proto, test_user)
    items = await list_runs_awaiting_signoff_for_user(
        db_session, test_user.id, [run], _facts([run]), {run.id: []}
    )
    assert len(items) == 1
    assert items[0].kind == "run"
    assert items[0].detail == "Missing OPERATOR"


@pytest.mark.asyncio
async def test_incomplete_steps_excluded(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project)
    run = await _run(db_session, test_project, proto, test_user, completed=False)
    items = await list_runs_awaiting_signoff_for_user(
        db_session, test_user.id, [run], _facts([run]), {run.id: []}
    )
    assert items == []


@pytest.mark.asyncio
async def test_non_glp_excluded(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project, enabled=False)
    run = await _run(db_session, test_project, proto, test_user)
    items = await list_runs_awaiting_signoff_for_user(
        db_session, test_user.id, [run], _facts([run]), {run.id: []}
    )
    assert items == []


@pytest.mark.asyncio
async def test_all_roles_signed_excluded(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project)
    run = await _run(db_session, test_project, proto, test_user)
    db_session.add(_approved_signoff(run.id, "OPERATOR", test_user.id))
    await db_session.flush()
    items = await list_runs_awaiting_signoff_for_user(
        db_session, test_user.id, [run], _facts([run]), {run.id: []}
    )
    assert items == []


@pytest.mark.asyncio
async def test_not_involved_excluded(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project)
    run = await _run(db_session, test_project, proto, test_user)
    run.started_by_id = None  # remove the only involvement link
    await db_session.flush()
    items = await list_runs_awaiting_signoff_for_user(
        db_session, uuid4(), [run], _facts([run]), {run.id: []}
    )
    assert items == []


@pytest.mark.asyncio
async def test_edited_run_qualifies(
    db_session: AsyncSession, test_project: Project, test_user: User
):
    proto = await _glp_protocol(db_session, test_project)
    run = await _run(db_session, test_project, proto, test_user, status="EDITED")
    items = await list_runs_awaiting_signoff_for_user(
        db_session, test_user.id, [run], _facts([run]), {run.id: []}
    )
    assert len(items) == 1

"""Smoke test for the shared GLP fixtures introduced in F-0087 Task 41.0.

The single test depends on every backend GLP fixture and asserts that each
loads without erroring and exposes the headline fields downstream drift
tests (Task 41a) and Playwright golden paths (Task 41b) rely on.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.equipment import Equipment
from app.models.iam import Organization, User
from app.models.protocols import Protocol, ProtocolRole
from app.models.runs import Run, RunOutcome, RunStatus


@pytest.mark.asyncio
async def test_glp_fixtures_load(
    glp_org: Organization,
    study_director_user: User,
    qau_user: User,
    operator_user: User,
    glp_protocol: Protocol,
    glp_run_planned: Run,
    glp_run_active: Run,
    glp_run_completed: Run,
    fresh_equipment: Equipment,
    imminent_equipment: Equipment,
    expired_equipment: Equipment,
    db_session,
) -> None:
    # Org
    assert glp_org.id is not None

    # Users
    for u in (study_director_user, qau_user, operator_user):
        assert u.id is not None
        assert u.signature_full_path
        assert u.email_verified is True

    # Protocol — GLP enabled, two lanes, three unit-op nodes
    assert glp_protocol.id is not None
    assert glp_protocol.graph["glpSettings"]["glp_enabled"] is True
    nodes = glp_protocol.graph["nodes"]
    swimlanes = [n for n in nodes if n["type"] == "swimLane"]
    unit_ops = [n for n in nodes if n["type"] == "unitOp"]
    assert len(swimlanes) == 2
    assert len(unit_ops) == 3

    from sqlalchemy import select

    roles_res = await db_session.execute(
        select(ProtocolRole).where(ProtocolRole.protocol_id == glp_protocol.id)
    )
    roles = roles_res.scalars().all()
    assert len(roles) == 2

    # Runs — three lifecycle stages
    assert glp_run_planned.status == RunStatus.PLANNED
    assert glp_run_planned.started_by_id is None

    assert glp_run_active.status == RunStatus.ACTIVE
    assert glp_run_active.started_by_id == operator_user.id
    assert glp_run_active.started_at is not None

    assert glp_run_completed.status == RunStatus.COMPLETED
    assert glp_run_completed.completed_at is not None
    assert glp_run_completed.outcome == RunOutcome.COMPLETED_NORMAL.value

    # Equipment — three calibration states
    today = date.today()
    assert fresh_equipment.next_calibration_date > today + timedelta(days=30)
    assert (
        today < imminent_equipment.next_calibration_date <= today + timedelta(days=14)
    )
    assert expired_equipment.next_calibration_date < today

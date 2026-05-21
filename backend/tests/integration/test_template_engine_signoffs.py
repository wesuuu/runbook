"""Integration tests for F-0087 template engine GLP context.

Asserts that :func:`build_context` (fed by
:func:`assemble_signoff_context_args`) exposes:

* ``ctx["signoffs"][role_lower]`` for run sign-offs
* ``ctx["protocol_approvals"][role_lower]`` for protocol sign-offs
* ``ctx["approval"]`` back-compat alias (QAU > SD > sponsor)
* ``ctx["run"]["outcome"]`` / ``ctx["run"]["outcome_notes"]``
* ``ctx["equipment"][i]`` with serial_number / calibration_due_at /
  calibration_status

The async DB-side gathering is split into ``assemble_signoff_context_args``
so the existing synchronous ``build_context`` keeps working for the 14+
template-rendering tests in ``tests/unit/test_template_engine.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.iam import User
from app.models.protocols import Protocol
from app.models.runs import Run
from app.models.signoffs import GlpSignoff
from app.services.protocols.template_engine import (
    assemble_signoff_context_args,
    build_context,
)


def _signoff(
    *,
    run_id=None,
    protocol_id=None,
    role: str,
    signer_id,
    signed_at: datetime | None = None,
) -> GlpSignoff:
    """Build an APPROVED GlpSignoff with the CHECK-constraint fields set."""
    return GlpSignoff(
        run_id=run_id,
        protocol_id=protocol_id,
        role=role,
        action="APPROVED",
        signer_id=signer_id,
        attestation=f"I attest as {role}.",
        signature_image_path=f"/signatures/{role.lower()}.png",
        signed_at=signed_at or datetime.now(timezone.utc),
    )


@pytest_asyncio.fixture
async def protocol_fixture(db_session: AsyncSession, test_project) -> Protocol:
    proto = Protocol(
        name="GLP Template Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=2,
        graph={"nodes": [], "edges": []},
        slug="glp-template-protocol",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def completed_run_with_signoffs(
    db_session: AsyncSession,
    test_project,
    test_user: User,
    protocol_fixture: Protocol,
) -> Run:
    """COMPLETED run with an OPERATOR sign-off plus protocol QAU approval."""
    run = Run(
        name="GLP Run with Signoffs",
        project_id=test_project.id,
        protocol_id=protocol_fixture.id,
        status="COMPLETED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        completed_at=datetime.now(timezone.utc),
        outcome="COMPLETED",
        slug="glp-run-with-signoffs",
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(_signoff(run_id=run.id, role="OPERATOR", signer_id=test_user.id))
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def approved_protocol_with_qau_signoff(
    db_session: AsyncSession,
    test_user: User,
    protocol_fixture: Protocol,
) -> Protocol:
    """Protocol carrying an active QAU + SD sign-off (QAU wins back-compat)."""
    db_session.add(
        _signoff(
            protocol_id=protocol_fixture.id,
            role="STUDY_DIRECTOR",
            signer_id=test_user.id,
            signed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.add(
        _signoff(
            protocol_id=protocol_fixture.id,
            role="QAU",
            signer_id=test_user.id,
            signed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()
    return protocol_fixture


@pytest_asyncio.fixture
async def run_with_calibrated_equipment(
    db_session: AsyncSession,
    test_org,
    test_project,
) -> Run:
    """Run whose graph references one Equipment row with a future cal date."""
    eq = Equipment(
        organization_id=test_org.id,
        name="HPLC #1",
        serial_number="HPLC-001",
        next_calibration_date=date.today() + timedelta(days=30),
    )
    db_session.add(eq)
    await db_session.flush()
    run = Run(
        name="GLP Run with Equipment",
        project_id=test_project.id,
        status="ACTIVE",
        graph={
            "nodes": [
                {
                    "id": "n1",
                    "type": "unitOp",
                    "data": {
                        "equipment": [{"local_id": "hplc", "equipment_id": str(eq.id)}]
                    },
                }
            ],
            "edges": [],
        },
        execution_data={},
        notes=[],
        attachments=[],
        slug="glp-run-with-equipment",
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def completed_run_with_outcome(
    db_session: AsyncSession,
    test_project,
) -> Run:
    run = Run(
        name="GLP Run with Outcome",
        project_id=test_project.id,
        status="COMPLETED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        completed_at=datetime.now(timezone.utc),
        outcome="COMPLETED_WITH_DEVIATIONS",
        outcome_notes="Two minor deviations logged on steps 3 and 7.",
        slug="glp-run-with-outcome",
    )
    db_session.add(run)
    await db_session.flush()
    return run


# ────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_includes_run_signoffs(
    db_session: AsyncSession, completed_run_with_signoffs: Run
):
    kwargs = await assemble_signoff_context_args(
        db_session, run=completed_run_with_signoffs
    )
    ctx, _ = build_context(
        protocol_name="Test",
        run_name=completed_run_with_signoffs.name,
        **kwargs,
    )
    assert "signoffs" in ctx
    op = ctx["signoffs"]["operator"]
    assert op["name"]
    assert op["signature_image"] == "/signatures/operator.png"
    assert op["attestation"]
    assert op["signed_at"]
    assert op["initials"]


@pytest.mark.asyncio
async def test_context_includes_protocol_approvals(
    db_session: AsyncSession,
    approved_protocol_with_qau_signoff: Protocol,
):
    kwargs = await assemble_signoff_context_args(
        db_session, protocol=approved_protocol_with_qau_signoff
    )
    ctx, _ = build_context(
        protocol_name=approved_protocol_with_qau_signoff.name, **kwargs
    )
    assert ctx["protocol_approvals"]["qau"]["name"]
    assert ctx["protocol_approvals"]["study_director"]["name"]


@pytest.mark.asyncio
async def test_context_includes_equipment_calibration(
    db_session: AsyncSession, run_with_calibrated_equipment: Run
):
    kwargs = await assemble_signoff_context_args(
        db_session, run=run_with_calibrated_equipment
    )
    ctx, _ = build_context(
        protocol_name="Test",
        run_name=run_with_calibrated_equipment.name,
        **kwargs,
    )
    assert ctx["equipment"], "expected equipment list to be populated"
    eq = ctx["equipment"][0]
    assert eq["serial_number"] == "HPLC-001"
    assert eq["calibration_due_at"] is not None
    assert eq["calibration_status"] in ("OK", "OVERDUE", "UNKNOWN")
    assert eq["calibration_status"] == "OK"


@pytest.mark.asyncio
async def test_context_includes_run_outcome(
    db_session: AsyncSession, completed_run_with_outcome: Run
):
    kwargs = await assemble_signoff_context_args(
        db_session, run=completed_run_with_outcome
    )
    ctx, _ = build_context(
        protocol_name="Test",
        run_name=completed_run_with_outcome.name,
        **kwargs,
    )
    assert ctx["run"]["outcome"] == "COMPLETED_WITH_DEVIATIONS"
    assert ctx["run"]["outcome_notes"]


@pytest.mark.asyncio
async def test_context_has_back_compat_approval_alias(
    db_session: AsyncSession,
    approved_protocol_with_qau_signoff: Protocol,
):
    """One-release back-compat: ``approval`` mirrors the QAU sign-off so
    user-uploaded templates referencing ``approval.*`` keep working."""
    kwargs = await assemble_signoff_context_args(
        db_session, protocol=approved_protocol_with_qau_signoff
    )
    ctx, _ = build_context(
        protocol_name=approved_protocol_with_qau_signoff.name,
        version_number=approved_protocol_with_qau_signoff.version_number,
        **kwargs,
    )
    assert "approval" in ctx
    assert ctx["approval"]["approver_name"] == ctx["protocol_approvals"]["qau"]["name"]
    assert (
        ctx["approval"]["signature_statement"]
        == ctx["protocol_approvals"]["qau"]["attestation"]
    )
    assert ctx["approval"]["protocol_version"] == 2


@pytest.mark.asyncio
async def test_overdue_equipment_flagged_as_overdue(
    db_session: AsyncSession, test_org, test_project
):
    """Calibration date in the past flips status to OVERDUE."""
    eq = Equipment(
        organization_id=test_org.id,
        name="Balance #7",
        serial_number="BAL-007",
        next_calibration_date=date.today() - timedelta(days=5),
    )
    db_session.add(eq)
    await db_session.flush()
    run = Run(
        name="Overdue Equipment Run",
        project_id=test_project.id,
        status="ACTIVE",
        graph={
            "nodes": [
                {
                    "id": "n1",
                    "type": "unitOp",
                    "data": {
                        "equipment": [{"local_id": "bal", "equipment_id": str(eq.id)}]
                    },
                }
            ],
            "edges": [],
        },
        execution_data={},
        notes=[],
        attachments=[],
        slug="overdue-equipment-run",
    )
    db_session.add(run)
    await db_session.flush()
    kwargs = await assemble_signoff_context_args(db_session, run=run)
    ctx, _ = build_context(protocol_name="Test", run_name=run.name, **kwargs)
    assert ctx["equipment"][0]["calibration_status"] == "OVERDUE"

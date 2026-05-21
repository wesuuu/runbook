"""Run QAU sign-off authorization via an open request (F-0080, audit fix H2)."""

import pytest
from fastapi import HTTPException

from app.models.signoffs import GlpSignoffRequest
from app.services.signoffs.validation import validate_signoff_role_assignable


@pytest.mark.asyncio
async def test_assigned_qau_request_authorizes_signer(
    db_session, glp_run_completed, qau_user,
):
    """An OPEN QAU request assigned to the signer authorizes the sign-off,
    even though qau_user is not designated in the protocol's glpSettings."""
    db_session.add(
        GlpSignoffRequest(
            run_id=glp_run_completed.id, role="QAU", status="OPEN",
            requested_user_id=qau_user.id,
        )
    )
    await db_session.flush()
    # Must not raise.
    await validate_signoff_role_assignable(
        db_session, "run", glp_run_completed.id, qau_user.id, "QAU"
    )


@pytest.mark.asyncio
async def test_unassigned_pool_request_authorizes_org_qau(
    db_session, glp_run_completed, qau_user,
):
    """An OPEN *unassigned* QAU request authorizes any org QAU (the pool)."""
    db_session.add(
        GlpSignoffRequest(run_id=glp_run_completed.id, role="QAU", status="OPEN")
    )
    await db_session.flush()
    # qau_user holds OrgRole.QAU → authorized via the pool. Must not raise.
    await validate_signoff_role_assignable(
        db_session, "run", glp_run_completed.id, qau_user.id, "QAU"
    )


@pytest.mark.asyncio
async def test_unassigned_pool_request_rejects_non_qau(
    db_session, glp_run_completed, operator_user,
):
    """An unassigned pool request must NOT authorize a non-QAU signer. With no
    designation and no protocol APPROVE permission, the signer is rejected."""
    db_session.add(
        GlpSignoffRequest(run_id=glp_run_completed.id, role="QAU", status="OPEN")
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await validate_signoff_role_assignable(
            db_session, "run", glp_run_completed.id, operator_user.id, "QAU"
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "ROLE_NOT_AUTHORIZED"

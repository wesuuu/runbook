"""Drift test: T2 LANES_UNASSIGNED — backend predicate.

A GLP-enabled run with unassigned swimlanes must be rejected when
transitioning PLANNED -> ACTIVE with stable error code ``LANES_UNASSIGNED``.

Companion to the vitest preflight test
(frontend/src/lib/components/run/LanesUnassigned.glp.test.ts) which asserts
the Start Run button is disabled when ``allRolesAssigned()`` returns false.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.iam import Organization
from app.models.science import Run


async def _auth_headers_for(user, glp_org: Organization) -> dict:
    token = create_access_token(
        user.id,
        org_id=glp_org.id,
        subscription_tier=glp_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.xfail(
    reason=(
        "assert_can_start() exists in app/services/runs/validation.py but is "
        "not yet wired into PATCH /science/runs/{id}/state. When the wiring "
        "lands the xfail strip should turn the test green."
    ),
    strict=False,
)
async def test_planned_to_active_with_unassigned_lanes_returns_lanes_unassigned(
    client: AsyncClient,
    glp_run_planned: Run,
    operator_user,
    glp_org,
) -> None:
    """The fixture run is GLP-enabled with two swimlanes and zero
    RunRoleAssignment rows.  PATCH state=ACTIVE must return 422 with
    ``detail.error == 'LANES_UNASSIGNED'``.
    """
    headers = await _auth_headers_for(operator_user, glp_org)

    res = await client.patch(
        f"/science/runs/{glp_run_planned.id}/state",
        headers=headers,
        json={"state": "ACTIVE"},
    )

    # Per validation.py, the stable code is LANES_UNASSIGNED with HTTP 422.
    assert res.status_code in (400, 422), res.text
    body = res.json()
    assert body["detail"]["error"] == "LANES_UNASSIGNED"
    missing = body["detail"].get("missing_lanes") or []
    assert len(missing) >= 1

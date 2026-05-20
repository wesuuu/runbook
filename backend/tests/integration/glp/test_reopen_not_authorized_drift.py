"""Drift test: T2 REOPEN_NOT_AUTHORIZED — backend predicate.

A user without one of the authorized reopen tiers (Study Director on the
protocol, Org Admin, or Project Lead/ADMIN) must be rejected when calling
POST /science/runs/{id}/reopen with stable error code
``REOPEN_NOT_AUTHORIZED``.

Companion to the vitest preflight test
(frontend/src/lib/components/run/ReopenNotAuthorized.glp.test.ts) which
asserts the Reopen button is hidden/disabled for unauthorized users.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.iam import Organization
from app.models.runs import Run


async def _auth_headers_for(user, org: Organization) -> dict:
    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.xfail(
    reason=(
        "assert_can_reopen() exists in app/services/runs/validation.py but "
        "is not yet wired into POST /science/runs/{id}/reopen. The current "
        "endpoint allows any authenticated user to reopen, so the 403 "
        "REOPEN_NOT_AUTHORIZED code is unreachable until the wiring lands."
    ),
    strict=False,
)
async def test_reopen_unauthorized_user_returns_reopen_not_authorized(
    client: AsyncClient,
    glp_run_completed: Run,
    operator_user,
    glp_org,
) -> None:
    """``operator_user`` is a plain MEMBER (no ADMIN, not the Study Director,
    no project-level ADMIN permission). They must not be allowed to reopen
    the completed run.
    """
    headers = await _auth_headers_for(operator_user, glp_org)

    res = await client.post(
        f"/science/runs/{glp_run_completed.id}/reopen",
        headers=headers,
        json={"reason": "Attempting unauthorized reopen"},
    )

    assert res.status_code == 403, res.text
    body = res.json()
    assert body["detail"]["error"] == "REOPEN_NOT_AUTHORIZED"

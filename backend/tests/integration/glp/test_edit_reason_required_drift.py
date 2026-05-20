"""Drift test: T2 EDIT_REASON_REQUIRED — backend predicate.

Companion to the vitest preflight test
(frontend/src/lib/components/run/EditReasonRequired.glp.test.ts).

If the backend's error code or HTTP status diverges from the frontend
preflight, one of these two tests will fail — that's the drift signal.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.iam import Organization
from app.models.runs import Run


async def _auth_headers_for(operator_user, glp_org: Organization) -> dict:
    token = create_access_token(
        operator_user.id,
        org_id=glp_org.id,
        subscription_tier=glp_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_edited_transition_missing_edit_reason_returns_400_with_stable_code(
    client: AsyncClient,
    glp_run_active: Run,
    operator_user,
    glp_org,
) -> None:
    """PATCH /science/runs/{id}/state with a step delta but no edit_reason
    must return 400 with ``detail.error == 'EDIT_REASON_REQUIRED'``.
    """
    headers = await _auth_headers_for(operator_user, glp_org)

    res = await client.patch(
        f"/science/runs/{glp_run_active.id}/state",
        headers=headers,
        json={
            "state": "EDITED",
            "edit_reasons": {},
            "execution_data_delta": {"u1": {"value": 42}},
        },
    )

    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["error"] == "EDIT_REASON_REQUIRED"
    issues = body["detail"].get("issues") or []
    assert any(item.get("step_id") == "u1" for item in issues)


async def test_edited_transition_blank_edit_reason_returns_400(
    client: AsyncClient,
    glp_run_active: Run,
    operator_user,
    glp_org,
) -> None:
    """A whitespace-only edit_reason is treated as missing."""
    headers = await _auth_headers_for(operator_user, glp_org)

    res = await client.patch(
        f"/science/runs/{glp_run_active.id}/state",
        headers=headers,
        json={
            "state": "EDITED",
            "edit_reasons": {"u1": "   "},
            "execution_data_delta": {"u1": {"value": 99}},
        },
    )

    assert res.status_code == 400, res.text
    assert res.json()["detail"]["error"] == "EDIT_REASON_REQUIRED"


async def test_edited_transition_with_reason_succeeds(
    client: AsyncClient,
    glp_run_active: Run,
    operator_user,
    glp_org,
) -> None:
    """Sanity check: same payload with a real reason transitions to EDITED."""
    headers = await _auth_headers_for(operator_user, glp_org)

    res = await client.patch(
        f"/science/runs/{glp_run_active.id}/state",
        headers=headers,
        json={
            "state": "EDITED",
            "edit_reasons": {"u1": "probe drift on step u1"},
            "execution_data_delta": {"u1": {"value": 42}},
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "EDITED"

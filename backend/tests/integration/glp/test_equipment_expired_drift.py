"""Drift test: T2 EQUIPMENT_EXPIRED — backend predicate.

When a GLP-enabled run references an Equipment row whose
``next_calibration_date`` is in the past, the backend must reject the
PLANNED -> ACTIVE transition with stable error code ``EQUIPMENT_EXPIRED``
unless the payload includes ``confirmed_expired_equipment: True`` (per
grilling decision #4).

Companion to the vitest preflight test
(frontend/src/lib/components/run/EquipmentExpired.glp.test.ts) which
asserts the ConfirmDialog mounts on Start when expired equipment is
linked.

NOTE: at the time of writing, EQUIPMENT_EXPIRED is not present anywhere
in app/services/runs/validation.py (or any other backend module). This
test is marked xfail so the drift signal lights up when the predicate
ships; flipping ``strict=False`` (already set) just means xpass is OK.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.equipment import Equipment
from app.models.iam import Organization
from app.models.runs import Run


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
        "EQUIPMENT_EXPIRED predicate not yet implemented in F-0087. When "
        "added to app/services/runs/validation.py and wired into the "
        "PATCH /state endpoint this test should turn green."
    ),
    strict=False,
)
async def test_start_with_expired_equipment_returns_equipment_expired(
    client: AsyncClient,
    db_session,
    glp_run_planned: Run,
    expired_equipment: Equipment,
    operator_user,
    glp_org,
) -> None:
    """Link expired_equipment into a unit-op node on the planned run, then
    attempt to start it. The backend must reject with 400 and
    ``detail.error == 'EQUIPMENT_EXPIRED'``.
    """
    # Mutate the snapshot graph to wire expired_equipment into u1.
    graph = dict(glp_run_planned.graph)
    new_nodes = []
    for node in graph.get("nodes", []):
        if node.get("id") == "u1":
            node = dict(node)
            data = dict(node.get("data") or {})
            data["equipment"] = [{"equipment_id": str(expired_equipment.id)}]
            node["data"] = data
        new_nodes.append(node)
    graph["nodes"] = new_nodes
    glp_run_planned.graph = graph
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(glp_run_planned, "graph")
    await db_session.flush()

    headers = await _auth_headers_for(operator_user, glp_org)
    res = await client.patch(
        f"/runs/{glp_run_planned.id}/state",
        headers=headers,
        json={"state": "ACTIVE"},
    )

    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["error"] == "EQUIPMENT_EXPIRED"

"""TD-0091c amendment S: STEP_DEVIATION recipients are limited to
RunRoleAssignment.user_id (filtered by current VIEW). A user with VIEW
permission on the run but NO RunRoleAssignment must NOT be notified."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.notifications import Notification
from app.models.runs import Run, RunRoleAssignment


@pytest.mark.asyncio
async def test_viewer_without_role_assignment_not_notified(
    authed_admin_client, db_session, test_project, test_user, test_org,
):
    """C has VIEW on the run but no RunRoleAssignment; A is an assignee.
    A should receive the STEP_DEVIATION notification; C should not."""
    assignee_a = User(
        email=f"assignee-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Assignee A",
    )
    viewer_c = User(
        email=f"viewer-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Viewer C",
    )
    db_session.add_all([assignee_a, viewer_c])
    await db_session.flush()
    for u in (assignee_a, viewer_c):
        db_session.add(
            OrganizationMember(
                user_id=u.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
    await db_session.flush()

    run = Run(
        name=f"Negative Run {uuid4().hex[:6]}",
        project_id=test_project.id,
        status="EDITED",
        graph={
            "nodes": [
                {
                    "id": "step-1",
                    "type": "unitOp",
                    "data": {"label": "Step 1", "paramSchema": {}},
                },
            ],
            "edges": [],
        },
        execution_data={
            "step-1": {
                "status": "completed",
                "results": {"ph": "7.0"},
                "notes": "",
            },
        },
        notes=[],
        attachments=[],
        slug=f"neg-{uuid4().hex[:6]}",
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.RUN.value,
            object_id=run.id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    # A: assignee + VIEW
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=assignee_a.id,
            object_type=ObjectType.RUN.value,
            object_id=run.id,
            permission_level=PermissionLevel.VIEW.value,
        )
    )
    db_session.add(
        RunRoleAssignment(
            run_id=run.id,
            lane_node_id="lane-1",
            role_name="Operator",
            user_id=assignee_a.id,
        )
    )
    # C: VIEW only, no assignment
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=viewer_c.id,
            object_type=ObjectType.RUN.value,
            object_id=run.id,
            permission_level=PermissionLevel.VIEW.value,
        )
    )
    await db_session.flush()
    await db_session.commit()

    new_exec = {
        "step-1": {
            "status": "completed",
            "results": {"ph": "7.5"},
            "notes": "",
        },
    }
    resp = await authed_admin_client.put(
        f"/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200, resp.text

    notif_users = {
        n.user_id for n in (await db_session.execute(
            select(Notification).where(
                Notification.event_type == "STEP_DEVIATION",
            )
        )).scalars().all()
    }
    assert assignee_a.id in notif_users
    assert viewer_c.id not in notif_users

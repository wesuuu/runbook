"""TD-0091c: DELETE /runs/{run_id}/role-assignments/{assignment_id} emits
a ROLE_UNASSIGNED notification to the user being removed."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.notifications import Notification
from app.models.runs import Run, RunRoleAssignment


@pytest.mark.asyncio
async def test_delete_role_assignment_notifies_removed_user(
    authed_admin_client, db_session, test_project, test_user,
):
    target = User(
        email=f"target-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Target User",
    )
    db_session.add(target)
    await db_session.flush()

    run = Run(
        name="Role Unassign Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        slug=f"role-unassign-{uuid4().hex[:6]}",
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
    assignment = RunRoleAssignment(
        run_id=run.id,
        lane_node_id="lane-1",
        role_name="Operator",
        user_id=target.id,
    )
    db_session.add(assignment)
    await db_session.flush()
    await db_session.commit()

    resp = await authed_admin_client.delete(
        f"/runs/{run.id}/role-assignments/{assignment.id}",
    )
    assert resp.status_code == 200, resp.text

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == target.id,
            Notification.event_type == "ROLE_UNASSIGNED",
        )
    )).scalars().all()
    assert len(notifs) == 1
    assert run.name in notifs[0].message

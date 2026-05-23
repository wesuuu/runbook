"""TD-0091c: PUT /runs/{id} on an EDITED-status run emits a STEP_DEVIATION
notification to other assignees with current VIEW permission."""

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


def _make_graph_with_two_steps():
    return {
        "nodes": [
            {
                "id": "step-1",
                "type": "unitOp",
                "data": {"label": "Buffer Mix", "paramSchema": {}},
            },
            {
                "id": "step-2",
                "type": "unitOp",
                "data": {"label": "Seeding", "paramSchema": {}},
            },
        ],
        "edges": [],
    }


def _initial_exec_data():
    return {
        "step-1": {
            "status": "completed",
            "results": {"ph": "7.0"},
            "notes": "",
        },
        "step-2": {
            "status": "completed",
            "results": {"value": "ok"},
            "notes": "",
        },
    }


async def _seed_edited_run(
    db_session, project, owner_user, extra_assignees,
):
    """Create a run in EDITED status with RunRoleAssignments for owner_user
    and each user in extra_assignees, plus VIEW ObjectPermissions on the run."""
    run = Run(
        name=f"Dev Run {uuid4().hex[:6]}",
        project_id=project.id,
        status="EDITED",
        graph=_make_graph_with_two_steps(),
        execution_data=_initial_exec_data(),
        notes=[],
        attachments=[],
        slug=f"dev-run-{uuid4().hex[:6]}",
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=owner_user.id,
            object_type=ObjectType.RUN.value,
            object_id=run.id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    db_session.add(
        RunRoleAssignment(
            run_id=run.id,
            lane_node_id="lane-1",
            role_name="Operator",
            user_id=owner_user.id,
        )
    )
    for u in extra_assignees:
        db_session.add(
            ObjectPermission(
                principal_type=PrincipalType.USER,
                principal_id=u.id,
                object_type=ObjectType.RUN.value,
                object_id=run.id,
                permission_level=PermissionLevel.VIEW.value,
            )
        )
        db_session.add(
            RunRoleAssignment(
                run_id=run.id,
                lane_node_id="lane-1",
                role_name=f"Reviewer-{uuid4().hex[:4]}",
                user_id=u.id,
            )
        )
    await db_session.flush()
    await db_session.commit()
    return run


async def _make_org_member(db_session, test_org, label):
    from app.models.iam import OrganizationMember

    u = User(
        email=f"{label}-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name=label,
    )
    db_session.add(u)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_step_deviation_notifies_other_assignees(
    authed_admin_client, db_session, test_project, test_user, test_org,
):
    other = await _make_org_member(db_session, test_org, "other")
    run = await _seed_edited_run(
        db_session, test_project, test_user, [other],
    )

    new_exec = {
        "step-1": {
            "status": "completed",
            "results": {"ph": "7.5"},
            "notes": "",
        },
        "step-2": {
            "status": "completed",
            "results": {"value": "ok"},
            "notes": "",
        },
    }
    resp = await authed_admin_client.put(
        f"/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200, resp.text

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.event_type == "STEP_DEVIATION",
            Notification.user_id == other.id,
        )
    )).scalars().all()
    assert len(notifs) == 1
    assert run.name in notifs[0].message

    actor_notifs = (await db_session.execute(
        select(Notification).where(
            Notification.event_type == "STEP_DEVIATION",
            Notification.user_id == test_user.id,
        )
    )).scalars().all()
    assert len(actor_notifs) == 0


@pytest.mark.asyncio
async def test_step_deviation_one_notification_per_request(
    authed_admin_client, db_session, test_project, test_user, test_org,
):
    other = await _make_org_member(db_session, test_org, "other")
    run = await _seed_edited_run(
        db_session, test_project, test_user, [other],
    )

    # Edit both steps in one request
    new_exec = {
        "step-1": {
            "status": "completed",
            "results": {"ph": "7.5"},
            "notes": "",
        },
        "step-2": {
            "status": "completed",
            "results": {"value": "changed"},
            "notes": "",
        },
    }
    resp = await authed_admin_client.put(
        f"/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200, resp.text

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == other.id,
            Notification.event_type == "STEP_DEVIATION",
        )
    )).scalars().all()
    assert len(notifs) == 1
    assert "1 other step" in notifs[0].message

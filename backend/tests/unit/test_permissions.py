import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    Organization,
    OrganizationMember,
    Team,
    TeamMember,
    User,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
    Role,
)
from app.models.science import Project, Protocol, Run
from app.core.security import hash_password
from app.services.permissions import check_permission


# --- Helpers ---

async def _setup_org_and_user(db, is_admin=False):
    """Create an org and user with membership."""
    org = Organization(name="Perm Test Org")
    db.add(org)
    await db.flush()

    user = User(
        email=f"perm-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Test",
    )
    db.add(user)
    await db.flush()

    db.add(OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        is_admin=is_admin,
    ))
    await db.flush()
    return org, user


async def _create_project(db, org):
    project = Project(
        name="Test Project",
        organization_id=org.id,
    )
    db.add(project)
    await db.flush()
    return project


# --- Tests ---

@pytest.mark.asyncio
async def test_org_admin_full_access(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=True)
    project = await _create_project(db_session, org)

    result = await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.ADMIN,
    )
    assert result is True


@pytest.mark.asyncio
async def test_org_admin_no_cross_org(db_session: AsyncSession):
    org1, user = await _setup_org_and_user(db_session, is_admin=True)
    org2 = Organization(name="Other Org")
    db_session.add(org2)
    await db_session.flush()

    project = Project(name="Other Project", organization_id=org2.id)
    db_session.add(project)
    await db_session.flush()

    result = await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    )
    assert result is False


@pytest.mark.asyncio
async def test_individual_view_can_view(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    ) is True


@pytest.mark.asyncio
async def test_individual_view_cannot_edit(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.EDIT,
    ) is False


@pytest.mark.asyncio
async def test_individual_edit_can_edit(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.EDIT.value,
    ))
    await db_session.flush()

    # EDIT can view
    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    ) is True
    # EDIT can edit
    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.EDIT,
    ) is True


@pytest.mark.asyncio
async def test_team_perm_grants_member_access(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    team = Team(name="TestTeam", organization_id=org.id)
    db_session.add(team)
    await db_session.flush()

    db_session.add(TeamMember(
        user_id=user.id, team_id=team.id, role=Role.MEMBER,
    ))
    db_session.add(ObjectPermission(
        principal_type=PrincipalType.TEAM,
        principal_id=team.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    ) is True


@pytest.mark.asyncio
async def test_individual_overrides_team(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    team = Team(name="TestTeam", organization_id=org.id)
    db_session.add(team)
    await db_session.flush()

    db_session.add(TeamMember(
        user_id=user.id, team_id=team.id, role=Role.MEMBER,
    ))
    # Team has VIEW
    db_session.add(ObjectPermission(
        principal_type=PrincipalType.TEAM,
        principal_id=team.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))
    # Individual has EDIT (overrides team)
    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.EDIT.value,
    ))
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.EDIT,
    ) is True


@pytest.mark.asyncio
async def test_protocol_inherits_project(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))

    protocol = Protocol(
        name="Test Protocol",
        project_id=project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.PROTOCOL, protocol.id,
        PermissionLevel.VIEW,
    ) is True


@pytest.mark.asyncio
async def test_run_inherits_project(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=project.id,
        permission_level=PermissionLevel.EDIT.value,
    ))

    run_obj = Run(
        name="Test Run",
        project_id=project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    assert await check_permission(
        db_session, user.id,
        ObjectType.RUN, run_obj.id,
        PermissionLevel.EDIT,
    ) is True


@pytest.mark.asyncio
async def test_no_permission_denied(db_session: AsyncSession):
    org, user = await _setup_org_and_user(db_session, is_admin=False)
    project = await _create_project(db_session, org)

    # No permission granted at all
    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    ) is False


@pytest.mark.asyncio
async def test_non_org_member_denied(db_session: AsyncSession):
    org = Organization(name="Foreign Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email=f"foreign-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Foreign",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(name="Foreign Project", organization_id=org.id)
    db_session.add(project)
    await db_session.flush()

    # User not in org — even if they somehow have a perm row,
    # check_permission should deny because they're not an org member
    assert await check_permission(
        db_session, user.id,
        ObjectType.PROJECT, project.id,
        PermissionLevel.VIEW,
    ) is False

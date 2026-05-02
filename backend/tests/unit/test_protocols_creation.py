"""Tests for services/protocols/creation.py — thin protocol creation service."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            PermissionLevel, PrincipalType, User)
from app.models.science import Project, Protocol
from app.services.protocols.creation import (ProtocolSpec, ProtocolStep,
                                             create_protocol_from_spec,
                                             update_protocol_metadata)


@pytest_asyncio.fixture
async def project(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
) -> Project:
    p = Project(name="test-proj", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(p)
    await db_session.flush()
    perm = ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=test_user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=p.id,
        permission_level=PermissionLevel.EDIT.value,
    )
    db_session.add(perm)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_creates_protocol_from_spec(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    spec = ProtocolSpec(
        name="My Protocol",
        description="Bench-scale mAb",
        steps=[
            ProtocolStep(
                name="Buffer Mix", unit_op_name="Buffer Preparation", duration_min=15
            ),
            ProtocolStep(
                name="Inoculate", unit_op_name="Cell Seeding", duration_min=30
            ),
        ],
    )
    proto = await create_protocol_from_spec(
        db_session,
        user_id=test_user.id,
        project_name=project.name,
        spec=spec,
    )
    assert proto.name == "My Protocol"
    assert proto.project_id == project.id
    assert proto.status == "DRAFT"
    # 1 processStart + 2 step nodes; 2 edges chaining them
    assert len(proto.graph["nodes"]) == 3
    assert len(proto.graph["edges"]) == 2
    assert proto.graph["nodes"][0]["type"] == "processStart"


@pytest.mark.asyncio
async def test_raises_when_project_not_found(
    db_session: AsyncSession,
    test_user: User,
):
    spec = ProtocolSpec(
        name="X",
        description="",
        steps=[
            ProtocolStep(name="s", unit_op_name="s", duration_min=10),
        ],
    )
    with pytest.raises(ValueError, match="not found"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name="nonexistent",
            spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_without_edit_permission(
    db_session: AsyncSession,
    test_user: User,
):
    # Create a separate org/project that test_user is not a member of.
    other_org = Organization(name="other-org", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()

    p = Project(
        name="restricted-proj",
        organization_id=other_org.id,
        owner_id=uuid.uuid4(),
    )
    db_session.add(p)
    await db_session.flush()
    spec = ProtocolSpec(
        name="X",
        description="",
        steps=[
            ProtocolStep(name="s", unit_op_name="s", duration_min=10),
        ],
    )
    with pytest.raises(ValueError, match="permission"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name="restricted-proj",
            spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_when_spec_has_no_steps(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    spec = ProtocolSpec(name="X", description="", steps=[])
    with pytest.raises(ValueError, match="step"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name=project.name,
            spec=spec,
        )


@pytest.mark.asyncio
async def test_update_protocol_metadata_patches_name_and_description(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    proto = Protocol(
        name="Old", description="o", project_id=project.id, status="DRAFT", graph={}
    )
    db_session.add(proto)
    await db_session.flush()
    updated = await update_protocol_metadata(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
        name="New",
        description="n",
    )
    assert updated.name == "New"
    assert updated.description == "n"


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_on_published(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    proto = Protocol(
        name="P", project_id=project.id, status="APPROVED", version_number=1, graph={}
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_protocol_metadata(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="X",
        )


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_without_perm(
    db_session: AsyncSession,
    test_user: User,
):
    other_org = Organization(name="o2", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="op", organization_id=other_org.id, owner_id=uuid.uuid4())
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(name="X", project_id=proj.id, status="DRAFT", graph={})
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await update_protocol_metadata(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="Y",
        )

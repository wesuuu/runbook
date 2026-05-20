"""Tests for services/protocols/unit_ops.py — unit op creation service."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.projects import Project
from app.models.protocols import UnitOpDefinition
from app.services.protocols.unit_ops import (
    create_unit_op_definition,
    elevate_unit_op_scope,
    update_unit_op_definition,
)


@pytest.mark.asyncio
async def test_creates_org_scoped_unit_op_for_admin(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="Custom Mix",
        category="Buffer Prep",
        description="Mix Tris/HCl",
        param_schema={"properties": {}},
    )
    assert op.name == "Custom Mix"
    assert op.organization_id == test_org.id
    assert op.project_id is None


@pytest.mark.asyncio
async def test_rejects_org_scope_for_non_admin(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    with pytest.raises(ValueError, match="admin"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="org",
            name="X",
            category="X",
            description="X",
            param_schema={},
        )


@pytest.mark.asyncio
async def test_project_scope_requires_project_id(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    with pytest.raises(ValueError, match="project_id"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="project",
            project_id=None,
            name="X",
            category="X",
            description="X",
            param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_invalid_scope(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    with pytest.raises(ValueError, match="scope"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            scope="bogus",
            name="X",
            category="X",
            description="X",
            param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_duplicate_name(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="Dup",
        category="C",
        description="D",
        param_schema={},
    )
    with pytest.raises(ValueError, match="exists"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            scope="org",
            name="Dup",
            category="C",
            description="D",
            param_schema={},
        )


@pytest.mark.asyncio
async def test_update_unit_op_patches_fields(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="Mix",
        category="Buffer Prep",
        description="old",
        param_schema={"properties": {}},
    )
    updated = await update_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        unit_op_id=op.id,
        description="new",
        category="Cell Culture",
    )
    assert updated.description == "new"
    assert updated.category == "Cell Culture"
    assert updated.name == "Mix"  # unchanged


@pytest.mark.asyncio
async def test_update_org_scoped_op_requires_admin(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="OrgOp",
        category="C",
        description="d",
        param_schema={},
    )
    with pytest.raises(ValueError, match="admin"):
        await update_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            unit_op_id=op.id,
            description="x",
        )


@pytest.mark.asyncio
async def test_update_refuses_library_override(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    op = UnitOpDefinition(
        name="Lib",
        category="C",
        description="d",
        param_schema={},
        organization_id=test_org.id,
        project_id=None,
        source_library_slug="lib",
        source_op_slug="op",
    )
    db_session.add(op)
    await db_session.flush()
    with pytest.raises(ValueError, match="library"):
        await update_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            unit_op_id=op.id,
            description="x",
        )


@pytest.mark.asyncio
async def test_elevate_promotes_project_to_org(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    proj = Project(name="p", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=False,
        scope="project",
        project_id=proj.id,
        name="ProjOp",
        category="C",
        description="d",
        param_schema={},
    )
    elevated = await elevate_unit_op_scope(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        unit_op_id=op.id,
    )
    assert elevated.project_id is None
    assert elevated.organization_id == test_org.id


@pytest.mark.asyncio
async def test_elevate_requires_admin(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    proj = Project(name="p2", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=False,
        scope="project",
        project_id=proj.id,
        name="ProjOp2",
        category="C",
        description="d",
        param_schema={},
    )
    with pytest.raises(ValueError, match="admin"):
        await elevate_unit_op_scope(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            unit_op_id=op.id,
        )


@pytest.mark.asyncio
async def test_elevate_refuses_already_org(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="X",
        category="C",
        description="d",
        param_schema={},
    )
    with pytest.raises(ValueError, match="already"):
        await elevate_unit_op_scope(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            unit_op_id=op.id,
        )


@pytest.mark.asyncio
async def test_elevate_refuses_library_override(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    proj = Project(name="p3", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = UnitOpDefinition(
        name="LibProj",
        category="C",
        description="d",
        param_schema={},
        organization_id=test_org.id,
        project_id=proj.id,
        source_library_slug="lib",
        source_op_slug="op",
    )
    db_session.add(op)
    await db_session.flush()
    with pytest.raises(ValueError, match="library"):
        await elevate_unit_op_scope(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            unit_op_id=op.id,
        )


@pytest.mark.asyncio
async def test_elevate_refuses_name_collision(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    # Existing org-scoped op with name "Collide"
    await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="Collide",
        category="C",
        description="d",
        param_schema={},
    )
    # Project-scoped op with the same name (allowed because org-vs-project
    # are different rows; create_unit_op_definition's dup check would block
    # this so we insert directly)
    proj = Project(name="p4", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    proj_op = UnitOpDefinition(
        name="Collide",
        category="C",
        description="d",
        param_schema={},
        organization_id=test_org.id,
        project_id=proj.id,
    )
    db_session.add(proj_op)
    await db_session.flush()
    with pytest.raises(ValueError, match="already exists"):
        await elevate_unit_op_scope(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            unit_op_id=proj_op.id,
        )

"""Tests for services/protocols/unit_ops.py — unit op creation service."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.protocols.unit_ops import create_unit_op_definition


@pytest.mark.asyncio
async def test_creates_org_scoped_unit_op_for_admin(
    db_session: AsyncSession, test_org: Organization, test_user: User,
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
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="admin"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="org",
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_project_scope_requires_project_id(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="project_id"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="project",
            project_id=None,
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_invalid_scope(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="scope"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            scope="bogus",
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_duplicate_name(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id, is_org_admin=True,
        scope="org", name="Dup", category="C", description="D", param_schema={},
    )
    with pytest.raises(ValueError, match="exists"):
        await create_unit_op_definition(
            db_session, user_id=test_user.id, org_id=test_org.id, is_org_admin=True,
            scope="org", name="Dup", category="C", description="D", param_schema={},
        )

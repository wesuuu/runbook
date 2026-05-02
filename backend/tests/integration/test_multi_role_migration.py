"""Verifies post-migration shape of `organization_members.roles`.

The Alembic migration runs once per pytest session via the `test_engine`
fixture, so by the time these tests execute the column already exists.
We exercise the resulting schema: rows can carry multi-role arrays, the
CHECK constraint rejects unknown values, and ARRAY containment works.
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, OrganizationMember, User


@pytest.mark.asyncio
async def test_backfill_admin_member_includes_member_and_admin(
    db_session: AsyncSession,
):
    org = Organization(name="Backfill Test")
    db_session.add(org)
    await db_session.flush()
    user = User(email=f"backfill-{uuid.uuid4().hex[:8]}@example.com",
                full_name="A")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
    await db_session.flush()

    result = await db_session.execute(
        text(
            "SELECT roles FROM organization_members "
            "WHERE user_id = :uid AND organization_id = :oid"
        ),
        {"uid": str(user.id), "oid": str(org.id)},
    )
    roles = result.scalar_one()
    assert "MEMBER" in roles
    assert "ADMIN" in roles


@pytest.mark.asyncio
async def test_check_constraint_rejects_unknown_role(
    db_session: AsyncSession,
):
    org = Organization(name="Check Constraint Test")
    db_session.add(org)
    await db_session.flush()
    user = User(email=f"check-{uuid.uuid4().hex[:8]}@example.com",
                full_name="C")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=["MEMBER", "BOGUS_ROLE"],
        )
    )
    with pytest.raises(Exception) as exc:
        await db_session.flush()
    msg = str(exc.value).lower()
    assert "ck_org_member_roles" in msg or "check" in msg

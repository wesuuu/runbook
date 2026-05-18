"""Unit tests for require_any_org_role dependency factory.

Fixtures used:
- db_session, test_org, test_user (from conftest) — test_user has roles
  ["MEMBER", "ADMIN"] by default.
- A local `member_with_roles` helper fixture creates a fresh user + membership
  with a configurable role list, used to test non-ADMIN members.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.deps import require_any_org_role
from app.core.security import hash_password
from app.models.iam import OrganizationMember, OrgRole, User


@pytest_asyncio.fixture
async def member_with_roles(db_session, test_org):
    """Factory fixture: creates a user+membership with explicit roles list."""

    async def _make(roles: list[str]) -> User:
        user = User(
            email=f"role-test-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Role Test User",
            selected_org_id=test_org.id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=test_org.id,
                roles=roles,
            )
        )
        await db_session.flush()
        return user

    return _make


@pytest.mark.asyncio
async def test_member_with_required_role_passes(db_session, member_with_roles):
    """A user holding SITE_MANAGER passes a [SITE_MANAGER, ADMIN] rule."""
    user = await member_with_roles(["MEMBER", "SITE_MANAGER"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])
    result = await dep(user=user, db=db_session)
    assert result.id == user.id


@pytest.mark.asyncio
async def test_admin_only_member_rejected_without_admin_in_list(
    db_session, member_with_roles
):
    """A MEMBER-only user is rejected when SITE_MANAGER is required (no hierarchy)."""
    user = await member_with_roles(["MEMBER"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER])
    with pytest.raises(HTTPException) as exc:
        await dep(user=user, db=db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_passes_when_admin_in_list(db_session, member_with_roles):
    """An ADMIN user passes when ADMIN is explicitly in the allowed list."""
    user = await member_with_roles(["MEMBER", "ADMIN"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])
    result = await dep(user=user, db=db_session)
    assert result.id == user.id


@pytest.mark.asyncio
async def test_admin_rejected_when_not_in_list(db_session, member_with_roles):
    """An ADMIN is NOT implicitly granted — if ADMIN is absent from the list, rejected."""
    user = await member_with_roles(["MEMBER", "ADMIN"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER])
    with pytest.raises(HTTPException) as exc:
        await dep(user=user, db=db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_no_org_selected_raises_403(db_session, test_org):
    """A user with no selected_org_id receives 403."""
    user = User(
        email=f"no-org-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("testpass"),
        full_name="No Org User",
        selected_org_id=None,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    dep = require_any_org_role([OrgRole.SITE_MANAGER])
    with pytest.raises(HTTPException) as exc:
        await dep(user=user, db=db_session)
    assert exc.value.status_code == 403
    assert "No organization selected" in exc.value.detail

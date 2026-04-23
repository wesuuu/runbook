import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.core.deps import require_org_role
from app.models.iam import OrganizationMember, OrgRole


async def _replace_membership(db_session, user_id, org_id, role: str):
    """Delete the existing membership (created by test_user fixture) and insert a new one."""
    await db_session.execute(
        delete(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    db_session.add(OrganizationMember(
        user_id=user_id,
        organization_id=org_id,
        role=role,
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_admin_satisfies_billing_requirement(
    db_session, test_org, test_user
):
    await _replace_membership(
        db_session, test_user.id, test_org.id, OrgRole.ADMIN.value
    )
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_billing_satisfies_billing_requirement(
    db_session, test_org, test_user
):
    await _replace_membership(
        db_session, test_user.id, test_org.id, OrgRole.BILLING.value
    )
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_member_rejected_for_billing_requirement(
    db_session, test_org, test_user
):
    await _replace_membership(
        db_session, test_user.id, test_org.id, OrgRole.MEMBER.value
    )
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_no_membership_rejected(db_session, test_user):
    test_user.selected_org_id = None
    dep = require_org_role(OrgRole.BILLING)
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 403

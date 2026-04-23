import pytest
from fastapi import HTTPException

from app.core.deps import require_active_subscription


@pytest.mark.asyncio
async def test_active_status_passes(db_session, test_org, test_user):
    test_org.subscription_status = "active"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_trialing_status_passes(db_session, test_org, test_user):
    test_org.subscription_status = "trialing"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_null_status_passes_for_pre_billing_orgs(
    db_session, test_org, test_user
):
    test_org.subscription_status = None
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_canceled_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "canceled"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "subscription_required"
    assert exc.value.detail["status"] == "canceled"


@pytest.mark.asyncio
async def test_past_due_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "past_due"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_unpaid_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "unpaid"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402

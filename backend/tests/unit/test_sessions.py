"""Tests for the extracted sessions module."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.ai.sessions import (create_session, delete_session,
                                      get_session, list_sessions)


@pytest.mark.asyncio
async def test_creates_session_with_default_title(
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
):
    session = await create_session(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
    )
    assert session.title == "New Chat"
    assert session.user_id == test_user.id


@pytest.mark.asyncio
async def test_get_session_returns_none_for_missing(
    db_session: AsyncSession,
):
    result = await get_session(db_session, uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_sessions_returns_user_sessions(
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
):
    await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    sessions, total = await list_sessions(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
    )
    assert total >= 2
    assert all(s.user_id == test_user.id for s in sessions)


@pytest.mark.asyncio
async def test_delete_removes_session(
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
):
    session = await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    await delete_session(db_session, session)
    refetched = await get_session(db_session, session.id)
    assert refetched is None

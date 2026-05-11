"""Unit tests for _build_user_signatures helper.

Returns dict[user_id_str, dict[str, str]] with optional keys
'signature_initials_path' and 'signature_full_path'. Users with neither
path are omitted entirely.
"""

import pytest

from app.api.endpoints.protocol_pdfs import _build_user_signatures
from app.core.security import hash_password
from app.models.iam import User


async def _make_user(db_session, *, initials=None, full=None) -> User:
    user = User(
        email=f"u-{initials or ''}-{full or ''}-test@example.com",
        hashed_password=hash_password("test"),
        full_name="Test User",
        signature_initials_path=initials,
        signature_full_path=full,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_returns_full_path_when_user_has_one(db_session):
    user = await _make_user(db_session, full="system/sigs/full.png")

    result = await _build_user_signatures(db_session, [user.id])

    entry = result[str(user.id)]
    assert "signature_full_path" in entry
    assert entry["signature_full_path"].endswith("system/sigs/full.png")
    assert "signature_initials_path" not in entry


@pytest.mark.asyncio
async def test_returns_initials_path_when_user_has_one(db_session):
    user = await _make_user(db_session, initials="system/sigs/init.png")

    result = await _build_user_signatures(db_session, [user.id])

    entry = result[str(user.id)]
    assert "signature_initials_path" in entry
    assert entry["signature_initials_path"].endswith("system/sigs/init.png")
    assert "signature_full_path" not in entry


@pytest.mark.asyncio
async def test_returns_both_when_user_has_both(db_session):
    user = await _make_user(
        db_session,
        initials="system/sigs/init.png",
        full="system/sigs/full.png",
    )

    result = await _build_user_signatures(db_session, [user.id])

    entry = result[str(user.id)]
    assert "signature_initials_path" in entry
    assert "signature_full_path" in entry
    assert entry["signature_initials_path"].endswith("system/sigs/init.png")
    assert entry["signature_full_path"].endswith("system/sigs/full.png")


@pytest.mark.asyncio
async def test_skips_users_with_no_signatures(db_session):
    user = await _make_user(db_session)

    result = await _build_user_signatures(db_session, [user.id])

    assert str(user.id) not in result


@pytest.mark.asyncio
async def test_empty_input_returns_empty_dict(db_session):
    result = await _build_user_signatures(db_session, [])
    assert result == {}

"""Tests for OAuth fields migration and constraints."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, text

from app.models.iam import User


@pytest.mark.asyncio
async def test_oauth_fields_added(db_session: AsyncSession):
    """Verify OAuth fields exist and have correct defaults."""
    # Create a user without OAuth fields (traditional email/password user)
    user = User(
        email="test@example.com",
        hashed_password="hashed_pwd",
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()

    # Verify OAuth fields exist with correct defaults
    assert user.oauth_provider is None
    assert user.oauth_subject is None
    assert user.oauth_email_verified is False


@pytest.mark.asyncio
async def test_oauth_fields_nullable(db_session: AsyncSession):
    """Verify OAuth fields are nullable for traditional email/password users."""
    user = User(
        email="traditional@example.com",
        hashed_password="hashed_pwd",
    )
    db_session.add(user)
    await db_session.flush()

    # Verify user was created successfully with nullable OAuth fields
    refreshed_user = await db_session.scalar(
        select(User).where(User.email == "traditional@example.com")
    )
    assert refreshed_user is not None
    assert refreshed_user.oauth_provider is None
    assert refreshed_user.oauth_subject is None


@pytest.mark.asyncio
async def test_hashed_password_nullable(db_session: AsyncSession):
    """Verify hashed_password can be NULL for OAuth-only users."""
    # Create an OAuth-only user (no password)
    user = User(
        email="oauth@example.com",
        oauth_provider="google",
        oauth_subject="google_123",
        oauth_email_verified=True,
        hashed_password=None,  # OAuth users may not have a password
    )
    db_session.add(user)
    await db_session.flush()

    # Verify user was created with NULL password
    assert user.hashed_password is None
    assert user.oauth_provider == "google"
    assert user.oauth_subject == "google_123"


@pytest.mark.asyncio
async def test_oauth_unique_constraint_enforced(db_session: AsyncSession):
    """Verify unique constraint on (oauth_provider, oauth_subject) is enforced."""
    # Create first user with OAuth credentials
    user1 = User(
        email="alice@example.com",
        oauth_provider="google",
        oauth_subject="google_123",
        oauth_email_verified=True,
    )
    db_session.add(user1)
    await db_session.flush()

    # Try to create second user with same OAuth provider and subject
    user2 = User(
        email="bob@example.com",
        oauth_provider="google",
        oauth_subject="google_123",
        oauth_email_verified=True,
    )
    db_session.add(user2)

    # Should raise IntegrityError due to unique constraint
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_oauth_provider_unique_constraint_allows_nulls(db_session: AsyncSession):
    """Verify that multiple users can have NULL oauth_provider (unique allows multiple nulls)."""
    # Create first traditional user
    user1 = User(
        email="user1@example.com",
        hashed_password="pwd1",
    )
    db_session.add(user1)
    await db_session.flush()

    # Create second traditional user
    user2 = User(
        email="user2@example.com",
        hashed_password="pwd2",
    )
    db_session.add(user2)
    await db_session.flush()

    # Both should be created successfully (NULL, NULL is allowed in UNIQUE constraint)
    count = await db_session.scalar(
        select(text("COUNT(*)")).select_from(User)
    )
    assert count >= 2


@pytest.mark.asyncio
async def test_oauth_provider_different_providers_unique_subject(db_session: AsyncSession):
    """Verify same subject with different providers is allowed (composite uniqueness)."""
    # User with Google OAuth
    user1 = User(
        email="user1@example.com",
        oauth_provider="google",
        oauth_subject="12345",  # Same subject ID
        oauth_email_verified=True,
    )
    db_session.add(user1)
    await db_session.flush()

    # User with GitHub OAuth (different provider, same subject ID) should be allowed
    user2 = User(
        email="user2@example.com",
        oauth_provider="github",
        oauth_subject="12345",  # Same subject ID, different provider
        oauth_email_verified=True,
    )
    db_session.add(user2)
    await db_session.flush()

    # Both should exist
    users = await db_session.scalars(
        select(User).where(User.oauth_subject == "12345")
    )
    user_list = users.all()
    assert len(user_list) == 2
    assert {u.oauth_provider for u in user_list} == {"google", "github"}


@pytest.mark.asyncio
async def test_existing_users_unaffected(db_session: AsyncSession):
    """Verify existing email/password users remain unaffected by migration."""
    # Create several traditional users
    users_data = [
        {"email": "user1@example.com", "full_name": "User One"},
        {"email": "user2@example.com", "full_name": "User Two"},
        {"email": "user3@example.com", "full_name": "User Three"},
    ]

    for data in users_data:
        user = User(
            email=data["email"],
            full_name=data["full_name"],
            hashed_password="hashed_password",
        )
        db_session.add(user)

    await db_session.flush()

    # Verify all users created and OAuth fields are null
    for data in users_data:
        user = await db_session.scalar(
            select(User).where(User.email == data["email"])
        )
        assert user is not None
        assert user.oauth_provider is None
        assert user.oauth_subject is None
        assert user.oauth_email_verified is False
        assert user.full_name == data["full_name"]


@pytest.mark.asyncio
async def test_oauth_email_verified_default_false(db_session: AsyncSession):
    """Verify oauth_email_verified defaults to false."""
    # Create user with OAuth (not explicitly setting oauth_email_verified)
    user = User(
        email="newuser@example.com",
        oauth_provider="google",
        oauth_subject="abc123",
        # Intentionally not setting oauth_email_verified
    )
    db_session.add(user)
    await db_session.flush()

    assert user.oauth_email_verified is False


@pytest.mark.asyncio
async def test_mixed_auth_methods_coexist(db_session: AsyncSession):
    """Verify OAuth and traditional auth methods can coexist in database."""
    # Traditional user
    traditional_user = User(
        email="traditional@example.com",
        hashed_password="hashed_pwd",
        full_name="Traditional User",
    )
    db_session.add(traditional_user)

    # OAuth-only user
    oauth_user = User(
        email="oauth@example.com",
        oauth_provider="google",
        oauth_subject="google_xyz",
        oauth_email_verified=True,
        hashed_password=None,
    )
    db_session.add(oauth_user)

    # Hybrid user (both password and OAuth)
    hybrid_user = User(
        email="hybrid@example.com",
        hashed_password="hashed_pwd",
        oauth_provider="github",
        oauth_subject="github_abc",
        oauth_email_verified=True,
    )
    db_session.add(hybrid_user)

    await db_session.flush()

    # Verify all three created
    users = await db_session.scalars(select(User))
    user_list = users.all()
    assert len(user_list) >= 3

    # Verify each type
    trad = await db_session.scalar(
        select(User).where(User.email == "traditional@example.com")
    )
    assert trad.hashed_password is not None
    assert trad.oauth_provider is None

    oauth = await db_session.scalar(
        select(User).where(User.email == "oauth@example.com")
    )
    assert oauth.hashed_password is None
    assert oauth.oauth_provider == "google"

    hybrid = await db_session.scalar(
        select(User).where(User.email == "hybrid@example.com")
    )
    assert hybrid.hashed_password is not None
    assert hybrid.oauth_provider == "github"

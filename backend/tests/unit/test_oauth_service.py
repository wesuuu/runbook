import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.services.oauth import OAuthService, UserInfo
from app.models.iam import User
from app.core.security import hash_password


@pytest.fixture
async def oauth_service(db_session: AsyncSession):
    return OAuthService(db_session)


class TestOAuthService:

    @pytest.mark.asyncio
    async def test_get_or_create_user_new_oauth_user(
        self, oauth_service: OAuthService, db_session: AsyncSession
    ):
        """Test creating a new user via OAuth."""
        user_info = UserInfo(
            email="alice@example.com",
            oauth_subject="google-12345",
            email_verified=True,
        )

        user = await oauth_service.get_or_create_user("google", user_info)

        assert user.email == "alice@example.com"
        assert user.oauth_provider == "google"
        assert user.oauth_subject == "google-12345"
        assert user.oauth_email_verified is True
        assert user.hashed_password is None

    @pytest.mark.asyncio
    async def test_get_or_create_user_existing_oauth_user(
        self, oauth_service: OAuthService, db_session: AsyncSession
    ):
        """Test that existing OAuth user is returned."""
        user_info = UserInfo(
            email="bob@example.com",
            oauth_subject="google-67890",
            email_verified=True,
        )

        user1 = await oauth_service.get_or_create_user("google", user_info)
        user2 = await oauth_service.get_or_create_user("google", user_info)

        assert user1.id == user2.id

    @pytest.mark.asyncio
    async def test_get_or_create_user_email_conflict(
        self, oauth_service: OAuthService, db_session: AsyncSession
    ):
        """Test that OAuth fails if email exists with different auth method."""
        # Create email/password user first
        password_user = User(
            email="charlie@example.com",
            hashed_password=hash_password("password123"),
            oauth_provider=None,
            is_active=True,
        )
        db_session.add(password_user)
        await db_session.flush()

        # Try to create OAuth user with same email
        user_info = UserInfo(
            email="charlie@example.com",
            oauth_subject="google-99999",
            email_verified=True,
        )

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.get_or_create_user("google", user_info)

        assert exc_info.value.status_code == 409
        assert "already registered" in exc_info.value.detail

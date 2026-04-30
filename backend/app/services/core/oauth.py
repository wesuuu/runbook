import logging
from typing import NamedTuple, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iam import User

logger = logging.getLogger(__name__)


class UserInfo(NamedTuple):
    email: str
    oauth_subject: str
    email_verified: bool = False


class OAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_user(self, provider: str, user_info: UserInfo) -> User:
        """Look up or create user by OAuth provider + subject."""
        # Look up by oauth_provider + oauth_subject
        stmt = select(User).where(
            (User.oauth_provider == provider)
            & (User.oauth_subject == user_info.oauth_subject)
        )
        existing = await self.db.scalar(stmt)

        if existing:
            return existing

        # Check email conflict (different auth method)
        email_stmt = select(User).where(User.email == user_info.email)
        email_user = await self.db.scalar(email_stmt)

        if email_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered. Use that sign-in method.",
            )

        # Create new user
        new_user = User(
            email=user_info.email,
            hashed_password=None,
            oauth_provider=provider,
            oauth_subject=user_info.oauth_subject,
            oauth_email_verified=user_info.email_verified,
            email_verified=user_info.email_verified,
            is_active=True,
        )
        self.db.add(new_user)
        await self.db.flush()

        return new_user

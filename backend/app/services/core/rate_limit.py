from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatRateLimitAttempt


class RateLimitService:
    """Rate limit checker using database-backed storage.

    Can be swapped for Redis in the future without changing the interface.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        """Initialize with max attempts and time window (in seconds)."""
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    async def is_allowed(self, key: str, db: AsyncSession) -> bool:
        """Check if key is under the rate limit.

        Args:
            key: Unique identifier for the rate limit bucket
            db: Database session

        Returns:
            True if under limit, False if at/over limit
        """
        # Calculate the cutoff time (oldest allowed attempt)
        cutoff = datetime.utcnow() - timedelta(seconds=self.window_seconds)

        # Count attempts within the window
        result = await db.execute(
            select(func.count()).select_from(ChatRateLimitAttempt)
            .where(
                ChatRateLimitAttempt.key == key,
                ChatRateLimitAttempt.attempted_at >= cutoff
            )
        )
        count = result.scalar() or 0

        return count < self.max_attempts

    async def record_attempt(self, key: str, db: AsyncSession) -> None:
        """Record a new attempt for this key.

        Args:
            key: Unique identifier for the rate limit bucket
            db: Database session
        """
        attempt = ChatRateLimitAttempt(key=key, attempted_at=datetime.utcnow())
        db.add(attempt)
        await db.commit()

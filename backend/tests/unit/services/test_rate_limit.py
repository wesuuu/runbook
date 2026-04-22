import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.core.rate_limit import RateLimitService


@pytest.mark.asyncio
async def test_is_allowed_first_request(db_session: AsyncSession):
    """First request should always be allowed."""
    service = RateLimitService(max_attempts=1, window_seconds=3600)
    result = await service.is_allowed("test-key", db_session)
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_under_limit(db_session: AsyncSession):
    """Requests under limit should be allowed."""
    service = RateLimitService(max_attempts=3, window_seconds=3600)
    # Record 2 attempts
    await service.record_attempt("test-key-2", db_session)
    await service.record_attempt("test-key-2", db_session)
    # Third should be allowed
    result = await service.is_allowed("test-key-2", db_session)
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_over_limit(db_session: AsyncSession):
    """Requests over limit should be denied."""
    service = RateLimitService(max_attempts=2, window_seconds=3600)
    # Record 2 attempts (at limit)
    await service.record_attempt("test-key-3", db_session)
    await service.record_attempt("test-key-3", db_session)
    # Third should be denied
    result = await service.is_allowed("test-key-3", db_session)
    assert result is False



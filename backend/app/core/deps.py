from typing import Any, Sequence, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenPayload
from app.db.session import get_db
from app.models.iam import (TIER_RANK, ObjectType, PermissionLevel,
                            SubscriptionTier, User)
from app.services.core.permissions import check_permission

T = TypeVar("T")


async def get_or_404(
    db: AsyncSession,
    model: type[T],
    id: Any,
    *,
    detail: str | None = None,
    options: Sequence[Any] | None = None,
) -> T:
    """Fetch a single record by primary key or raise 404."""
    stmt = select(model).where(model.id == id)
    if options:
        for opt in options:
            stmt = stmt.options(opt)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(
            status_code=404,
            detail=detail or f"{model.__name__} not found",
        )
    return record


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    payload: TokenPayload | None = getattr(
        request.state, "token_payload", None
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    result = await db.execute(
        select(User).where(User.id == payload.user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_org_id_from_request(request: Request) -> UUID | None:
    """Extract org_id from the token payload stashed by AuthMiddleware."""
    payload: TokenPayload | None = getattr(
        request.state, "token_payload", None
    )
    if payload and payload.org_id:
        return payload.org_id
    return None


def require_permission(
    object_type: ObjectType,
    id_param: str,
    min_level: PermissionLevel,
):
    """Factory that returns a dependency function for permission checks.

    The returned function is a proper FastAPI dependency that reads the
    path parameter by name via the Request object.
    """

    async def _check(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        object_id = request.path_params.get(id_param)
        if object_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"Missing path parameter: {id_param}",
            )
        try:
            object_uuid = UUID(str(object_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID")

        allowed = await check_permission(
            db, user.id, object_type, object_uuid, min_level,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _check


def require_tier(min_tier: SubscriptionTier):
    """Factory that returns a dependency enforcing a minimum subscription tier.

    Reads the tier from the token payload stashed by AuthMiddleware.
    """

    async def _check(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        payload: TokenPayload | None = getattr(
            request.state, "token_payload", None
        )
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Subscription tier information unavailable",
            )
        current_tier = SubscriptionTier(payload.subscription_tier)
        if TIER_RANK[current_tier] < TIER_RANK[min_tier]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_tier.value} tier or above",
            )
        return user

    return _check


async def get_current_user_or_offline(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[User, dict | None]:
    """Authenticate with either a normal token or an offline token.

    Returns (user, offline_payload) where offline_payload is None for
    normal tokens, or the full JWT payload dict for offline tokens.
    """
    offline_payload: dict | None = getattr(
        request.state, "offline_payload", None
    )
    token_payload: TokenPayload | None = getattr(
        request.state, "token_payload", None
    )

    if offline_payload is not None:
        # Check if token is revoked
        from app.models.offline import RevokedOfflineToken
        jti = offline_payload.get("jti")
        revoked = await db.execute(
            select(RevokedOfflineToken).where(RevokedOfflineToken.jti == jti)
        )
        if revoked.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Offline token has been revoked",
            )
        user_id = UUID(offline_payload["sub"])
    elif token_payload is not None:
        user_id = token_payload.user_id
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user, offline_payload

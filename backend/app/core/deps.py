from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, decode_offline_token
from app.db.session import get_db
from app.models.iam import User, ObjectType, PermissionLevel
from app.services.permissions import check_permission

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
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
    return user


class RequirePermission:
    """Dependency that checks object-level permissions via path params.

    Usage:
        @router.get("/{project_id}")
        async def get_project(
            project_id: UUID,
            _perm=Depends(RequirePermission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )),
            ...
        )
    """

    def __init__(
        self,
        object_type: ObjectType,
        id_param: str,
        min_level: PermissionLevel,
    ):
        self.object_type = object_type
        self.id_param = id_param
        self.min_level = min_level

    async def __call__(
        self,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        **kwargs,
    ) -> User:
        # FastAPI doesn't inject path params via **kwargs for callables.
        # We use a wrapper approach instead — see require_permission().
        raise NotImplementedError(
            "Use require_permission() factory instead"
        )


def require_permission(
    object_type: ObjectType,
    id_param: str,
    min_level: PermissionLevel,
):
    """Factory that returns a dependency function for permission checks.

    The returned function is a proper FastAPI dependency that reads the
    path parameter by name via the Request object.
    """
    from fastapi import Request

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


async def get_current_user_or_offline(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, dict | None]:
    """Authenticate with either a normal token or an offline token.

    Returns (user, offline_payload) where offline_payload is None for
    normal tokens, or the full JWT payload dict for offline tokens.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token_str = credentials.credentials

    # Try offline token first (has "scope": "offline")
    offline_payload = decode_offline_token(token_str)
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
    else:
        # Fall back to normal token
        user_id = decode_access_token(token_str)
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
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

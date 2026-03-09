from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(
        plain.encode("utf-8"), hashed.encode("utf-8")
    )


def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(
        payload, settings.secret_key, algorithm=settings.jwt_algorithm
    )


def create_offline_token(user_id: UUID, run_id: UUID, days: int = 7) -> tuple[str, str, datetime]:
    """Create a scoped offline JWT for field mode.

    Returns (token, jti, expires_at).
    """
    jti = str(uuid4())
    expire = datetime.now(timezone.utc) + timedelta(days=days)
    payload = {
        "sub": str(user_id),
        "run_id": str(run_id),
        "scope": "offline",
        "jti": jti,
        "exp": expire,
    }
    token = jwt.encode(
        payload, settings.secret_key, algorithm=settings.jwt_algorithm
    )
    return token, jti, expire


def decode_access_token(token: str) -> UUID | None:
    try:
        payload = jwt.decode(
            token, settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        sub = payload.get("sub")
        if sub is None:
            return None
        return UUID(sub)
    except (JWTError, ValueError):
        return None


def decode_offline_token(token: str) -> Optional[dict]:
    """Decode an offline token. Returns full payload or None."""
    try:
        payload = jwt.decode(
            token, settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        if payload.get("scope") != "offline":
            return None
        if not payload.get("sub") or not payload.get("run_id") or not payload.get("jti"):
            return None
        return payload
    except (JWTError, ValueError):
        return None

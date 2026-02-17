from datetime import datetime, timedelta, timezone
from uuid import UUID

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

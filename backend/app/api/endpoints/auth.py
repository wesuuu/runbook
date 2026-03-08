import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.db.session import get_db
from app.models.iam import User
from app.schemas.auth import (
    LoginRequest,
    PasswordChange,
    PreferencesUpdate,
    ProfileUpdate,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter()

AVATARS_DIR = Path("./uploads/avatars")
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB


def _user_response(user: User) -> UserResponse:
    """Build UserResponse with computed avatar_url."""
    avatar_url = None
    if user.avatar_path:
        avatar_url = f"/uploads/avatars/{user.avatar_path}"
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        avatar_url=avatar_url,
        preferences=user.preferences or {},
        is_active=user.is_active,
    )


@router.post("/register", response_model=TokenResponse)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    if not settings.auth_enabled:
        if user is None:
            result = await db.execute(select(User).limit(1))
            user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth is disabled but no users exist in the database",
            )
    elif user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _user_response(user)


@router.put("/me", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.job_title is not None:
        user.job_title = body.job_title
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type} not allowed. Use JPEG, PNG, or WebP.",
        )

    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Avatar must be under 5 MB.",
        )

    ext = file.content_type.split("/")[-1]
    if ext == "jpeg":
        ext = "jpg"
    filename = f"{user.id}.{ext}"

    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old avatar if different extension
    if user.avatar_path and user.avatar_path != filename:
        old_path = AVATARS_DIR / user.avatar_path
        if old_path.exists():
            old_path.unlink()

    dest = AVATARS_DIR / filename
    dest.write_bytes(content)

    user.avatar_path = filename
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.avatar_path:
        old_path = AVATARS_DIR / user.avatar_path
        if old_path.exists():
            old_path.unlink()
        user.avatar_path = None
        await db.commit()
        await db.refresh(user)
    return _user_response(user)


@router.put("/me/preferences", response_model=UserResponse)
async def update_preferences(
    body: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = dict(user.preferences or {})
    if body.font_size is not None:
        if body.font_size not in ("small", "medium", "large"):
            raise HTTPException(400, "font_size must be small, medium, or large")
        prefs["font_size"] = body.font_size
    if body.density is not None:
        if body.density not in ("compact", "comfortable"):
            raise HTTPException(400, "density must be compact or comfortable")
        prefs["density"] = body.density
    user.preferences = prefs
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.put("/me/password")
async def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect.",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="New password must be at least 8 characters.",
        )
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}

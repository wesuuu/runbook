import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_verification_jwt,
    generate_verification_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.iam import Organization, OrganizationMember, User, VerificationToken
from app.schemas.auth import (
    LoginRequest,
    PasswordChange,
    PreferencesUpdate,
    ProfileUpdate,
    RegisterRequest,
    ResendVerificationResponse,
    TokenResponse,
    UserResponse,
    VerificationTokenResponse,
)
from app.services.email_service import get_email_provider

logger = logging.getLogger(__name__)
router = APIRouter()

AVATARS_DIR = Path("./uploads/avatars")
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB


# ---------- helpers ----------


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
        email_verified=user.email_verified,
    )


async def _send_verification_email(email: str, token: str) -> None:
    """Send verification email. Fire-and-forget — logs errors."""
    verify_url = (
        f"{settings.backend_url}/auth/verify-email"
        f"?token={token}&email={email}"
    )
    html_body = f"""<div style="font-family: sans-serif; max-width: 600px;">
  <h2 style="color: #1a1a1a;">Verify your email</h2>
  <p style="color: #333; line-height: 1.6;">
    Click the button below to verify your email address and activate your account.
  </p>
  <p style="margin: 24px 0;">
    <a href="{verify_url}"
       style="background: #2563eb; color: white; padding: 12px 24px;
              border-radius: 6px; text-decoration: none; font-weight: 500;">
      Verify Email
    </a>
  </p>
  <p style="color: #666; font-size: 13px;">
    Or copy this link: {verify_url}
  </p>
  <p style="color: #999; font-size: 12px;">
    This link expires in {settings.verification_token_ttl_days} days.
  </p>
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin-top: 24px;">
  <p style="color: #9ca3af; font-size: 12px;">Batchrite — Laboratory Execution System</p>
</div>"""
    text_body = (
        f"Verify your email by visiting: {verify_url}\n\n"
        f"This link expires in {settings.verification_token_ttl_days} days."
    )
    try:
        provider = get_email_provider()
        await provider.send(
            to=email,
            subject="Verify your email — Batchrite",
            html_body=html_body,
            text_body=text_body,
        )
    except Exception:
        logger.exception("Failed to send verification email to %s", email)


# ---------- register ----------

VERIFY_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Verification Failed</title></head>
<body style="font-family: sans-serif; display: flex; justify-content: center;
             align-items: center; min-height: 100vh; background: #f9fafb;">
  <div style="text-align: center; max-width: 400px;">
    <h2 style="color: #dc2626;">Verification Failed</h2>
    <p style="color: #666;">{message}</p>
    <a href="{frontend_url}/register" style="color: #2563eb;">Create a new account</a>
  </div>
</body></html>"""


@router.post("/register", response_model=VerificationTokenResponse)
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

    org_name = (
        f"{body.full_name}'s Organization"
        if body.full_name
        else "My Organization"
    )
    org = Organization(name=org_name)
    db.add(org)
    await db.flush()

    # Stamp system default templates
    from app.models.templates import DocumentTemplate

    for ttype, col in [
        ("SOP", "default_sop_template_id"),
        ("BATCH_RECORD", "default_batch_record_template_id"),
    ]:
        result = await db.execute(
            select(DocumentTemplate.id).where(
                DocumentTemplate.is_system == True,
                DocumentTemplate.is_default == True,
                DocumentTemplate.template_type == ttype,
            )
        )
        setattr(org, col, result.scalar_one_or_none())

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        selected_org_id=org.id,
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    db.add(OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role="ADMIN",
    ))

    # Create verification token
    token_str = generate_verification_token()
    db.add(VerificationToken(
        user_id=user.id,
        org_id=org.id,
        token=token_str,
        purpose="email_verification",
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.verification_token_ttl_days),
    ))

    await db.commit()
    await db.refresh(user)

    # Send email (fire-and-forget)
    await _send_verification_email(user.email, token_str)

    # Return temp JWT (scope=verification, 1hr)
    temp_jwt = create_verification_jwt(user.id, org_id=org.id)
    return VerificationTokenResponse(
        verification_token=temp_jwt,
        message="Check your email to verify your account",
    )


# ---------- verify email (public) ----------


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(
    token: str = Query(...),
    email: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    # Look up token
    result = await db.execute(
        select(VerificationToken).where(
            VerificationToken.token == token,
            VerificationToken.purpose == "email_verification",
            VerificationToken.used == False,
            VerificationToken.expires_at > datetime.now(timezone.utc),
        )
    )
    vt = result.scalar_one_or_none()

    if vt is None:
        return HTMLResponse(
            VERIFY_ERROR_HTML.format(
                message="This verification link is invalid or has expired.",
                frontend_url=settings.frontend_url,
            ),
            status_code=400,
        )

    # Load user and verify email matches
    user = await db.get(User, vt.user_id)
    if user is None or user.email != email:
        return HTMLResponse(
            VERIFY_ERROR_HTML.format(
                message="This verification link is invalid.",
                frontend_url=settings.frontend_url,
            ),
            status_code=400,
        )

    # Mark verified
    user.email_verified = True
    vt.used = True
    await db.commit()

    # Resolve org context for full JWT
    org_id = user.selected_org_id
    subscription_tier = "essentials"
    if org_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is not None:
            subscription_tier = org.subscription_tier

    jwt_token = create_access_token(
        user.id,
        org_id=org_id,
        subscription_tier=subscription_tier,
        email_verified=True,
    )
    # Redirect to frontend with token as query param
    # Frontend will extract it, store in localStorage, and redirect to /
    redirect_url = f"{settings.frontend_url}/?auth_token={jwt_token}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---------- resend verification ----------


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
)
async def resend_verification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.email_verified:
        raise HTTPException(
            status_code=400, detail="Email already verified"
        )

    # Rate limit: count tokens in window
    window_start = datetime.now(timezone.utc) - timedelta(
        minutes=settings.verification_resend_window_minutes
    )
    result = await db.execute(
        select(func.count()).select_from(VerificationToken).where(
            VerificationToken.user_id == user.id,
            VerificationToken.purpose == "email_verification",
            VerificationToken.created_at >= window_start,
        )
    )
    count = result.scalar()
    if count >= settings.verification_resend_limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )

    # Generate new token
    token_str = generate_verification_token()
    db.add(VerificationToken(
        user_id=user.id,
        org_id=user.selected_org_id,
        token=token_str,
        purpose="email_verification",
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.verification_token_ttl_days),
    ))
    await db.commit()

    await _send_verification_email(user.email, token_str)

    return ResendVerificationResponse(message="Verification email sent")


# ---------- login ----------


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

    # Resolve org context for the token
    org_id = user.selected_org_id
    subscription_tier = "essentials"
    if org_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is not None:
            subscription_tier = org.subscription_tier

    token = create_access_token(
        user.id,
        org_id=org_id,
        subscription_tier=subscription_tier,
        email_verified=user.email_verified,
    )
    return TokenResponse(access_token=token)


# ---------- me ----------


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

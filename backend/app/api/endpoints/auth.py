import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
from app.legal.service import get_current_version
from app.models.iam import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
    User,
    VerificationToken,
)
from app.schemas.auth import (
    LoginRequest,
    PasswordChange,
    PreferencesUpdate,
    ProfileUpdate,
    RegisterRequest,
    ResendVerificationResponse,
    SwitchOrgRequest,
    TokenResponse,
    UserResponse,
    VerificationTokenResponse,
    compute_tos_current,
)
from app.services.core.audit import log_audit
from app.services.core.email_service import get_email_provider
from app.services.core.file_storage import FileStorageService

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB

ALLOWED_SIGNATURE_TYPES = {"image/png"}
MAX_SIGNATURE_SIZE = 500 * 1024  # 500 KB
SIGNATURE_KINDS = {"initials", "full"}


def _signature_path_attr(kind: str) -> str:
    return "signature_initials_path" if kind == "initials" else "signature_full_path"


# ---------- helpers ----------


def _user_response(user: User) -> UserResponse:
    """Build UserResponse with computed avatar/signature URLs and tos_current."""
    avatar_url = None
    if user.avatar_path:
        avatar_url = f"/auth/avatars/{user.id}"
    signature_initials_url = None
    if user.signature_initials_path:
        signature_initials_url = f"/auth/signatures/{user.id}/initials"
    signature_full_url = None
    if user.signature_full_path:
        signature_full_url = f"/auth/signatures/{user.id}/full"
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        avatar_url=avatar_url,
        signature_initials_url=signature_initials_url,
        signature_full_url=signature_full_url,
        preferences=user.preferences or {},
        is_active=user.is_active,
        email_verified=user.email_verified,
        tos_accepted_at=user.tos_accepted_at,
        tos_version=user.tos_version,
        tos_current=compute_tos_current(user),
    )


async def _send_verification_email(email: str, token: str) -> None:
    """Send verification email. Fire-and-forget — logs errors."""
    verify_url = (
        f"{settings.backend_url}/auth/verify-email" f"?token={token}&email={email}"
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
        # Dev/local SMTP is often unconfigured; surface the link at WARNING
        # so a developer can verify without a working mail server. In prod
        # this also gives ops a fallback to recover users when SMTP breaks.
        logger.warning(
            "Email send failed for %s; verification link: %s",
            email,
            verify_url,
        )
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
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    org_name = (
        f"{body.full_name}'s Organization" if body.full_name else "My Organization"
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

    # F-0075: subscribe new org to default unit op libraries
    from app.services.science import library_registry

    await library_registry.subscribe_default_libraries(db, org.id)

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        selected_org_id=org.id,
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=["ADMIN", "MEMBER"],
        )
    )

    # Create Stripe trialing Essentials subscription (F-0019a).
    # No-op if Stripe is unconfigured (logs a warning); safe to call before commit.
    from app.services.billing.subscription_service import create_trial_subscription

    await create_trial_subscription(db, org, user)

    # Sync contact + lifecycle events to Loops (F-0019c).
    # No-op if Loops is unconfigured; failures are swallowed inside events.*
    from app.services.lifecycle import events as lifecycle_events

    lifecycle_events.emit_signup(user, org)
    lifecycle_events.emit_trial_started(user, org)

    # Seed "My First Project" for onboarding (F-0015)
    from app.models.science import Project

    db.add(
        Project(
            name="My First Project",
            description="Created for you — rename or delete as you like.",
            organization_id=org.id,
        )
    )

    # Create verification token
    token_str = generate_verification_token()
    db.add(
        VerificationToken(
            user_id=user.id,
            org_id=org.id,
            token=token_str,
            purpose="email_verification",
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.verification_token_ttl_days),
        )
    )

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
        raise HTTPException(status_code=400, detail="Email already verified")

    # Rate limit: count tokens in window
    window_start = datetime.now(timezone.utc) - timedelta(
        minutes=settings.verification_resend_window_minutes
    )
    result = await db.execute(
        select(func.count())
        .select_from(VerificationToken)
        .where(
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
    db.add(
        VerificationToken(
            user_id=user.id,
            org_id=user.selected_org_id,
            token=token_str,
            purpose="email_verification",
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.verification_token_ttl_days),
        )
    )
    await db.commit()

    await _send_verification_email(user.email, token_str)

    return ResendVerificationResponse(message="Verification email sent")


# ---------- login ----------


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == body.email))
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


# ---------- switch org ----------


@router.post("/switch-org", response_model=TokenResponse)
async def switch_org(
    body: SwitchOrgRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the user's selected org and return a new JWT."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == body.org_id,
            OrganizationMember.archived == False,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    user.selected_org_id = body.org_id
    await db.flush()

    # Resolve tier for the new org
    org_result = await db.execute(
        select(Organization).where(Organization.id == body.org_id)
    )
    org = org_result.scalar_one()

    await db.commit()

    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=user.email_verified,
    )
    return TokenResponse(access_token=token)


# ---------- accept invite ----------


INVITE_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Invitation Failed</title></head>
<body style="font-family: sans-serif; display: flex; justify-content: center;
             align-items: center; min-height: 100vh; background: #f9fafb;">
  <div style="text-align: center; max-width: 400px;">
    <h2 style="color: #dc2626;">Invitation Failed</h2>
    <p style="color: #666;">{message}</p>
    <a href="{frontend_url}" style="color: #2563eb;">Go to Batchrite</a>
  </div>
</body></html>"""


@router.get("/accept-invite", response_class=HTMLResponse)
async def accept_invite(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept an org invitation via email link."""
    result = await db.execute(
        select(Invitation).where(
            Invitation.token == token,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        return HTMLResponse(
            INVITE_ERROR_HTML.format(
                message="This invitation link is invalid or has already been used.",
                frontend_url=settings.frontend_url,
            ),
            status_code=400,
        )

    # Check expiry
    if invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = InvitationStatus.EXPIRED
        await db.commit()
        return HTMLResponse(
            INVITE_ERROR_HTML.format(
                message="This invitation has expired.",
                frontend_url=settings.frontend_url,
            ),
            status_code=400,
        )

    # Find the invited user by email
    user_result = await db.execute(
        select(User).where(User.email == invitation.invited_email)
    )
    invited_user = user_result.scalar_one_or_none()

    if invited_user is None:
        # No account — redirect to registration with invite token
        redirect_url = (
            f"{settings.frontend_url}/#/register" f"?invite={invitation.token}"
        )
        return RedirectResponse(url=redirect_url, status_code=302)

    # User exists — create org membership
    # Check for existing (possibly archived) membership
    existing_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == invited_user.id,
            OrganizationMember.organization_id == invitation.organization_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        if existing.archived:
            existing.archived = False
            existing.roles = sorted({"MEMBER", invitation.role})
        # else: already active member — no-op
    else:
        db.add(
            OrganizationMember(
                user_id=invited_user.id,
                organization_id=invitation.organization_id,
                roles=sorted({"MEMBER", invitation.role}),
            )
        )

    # Set selected_org_id if user doesn't have one (AC #2, #6)
    if invited_user.selected_org_id is None:
        invited_user.selected_org_id = invitation.organization_id

    invitation.status = InvitationStatus.ACCEPTED
    await db.commit()

    # Redirect to frontend
    redirect_url = f"{settings.frontend_url}/"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---------- me ----------


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _user_response(user)


@router.post("/accept-tos", response_model=UserResponse)
async def accept_tos(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the calling user's acceptance of the current Terms of
    Service and Privacy Policy version. Idempotent — repeated calls
    rewrite the User row's timestamp and write additional AuditLog rows.
    """
    version = get_current_version()
    user.tos_accepted_at = datetime.now(timezone.utc)
    user.tos_version = version

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await log_audit(
        db,
        actor_id=user.id,
        action="ACCEPT_TOS",
        entity_type="user",
        entity_id=user.id,
        changes={
            "version": version,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )

    await db.commit()
    await db.refresh(user)
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
    if not user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

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

    storage = FileStorageService()
    org_id = user.selected_org_id

    # Remove old avatar if it exists
    if user.avatar_path:
        try:
            storage.delete_file(user.avatar_path)
        except (OSError, ValueError):
            pass

    # Store new avatar at {org_id}/avatars/{user_id}.{ext}
    relative_path = str(Path(str(org_id)) / "avatars" / filename)
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)

    user.avatar_path = relative_path
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.avatar_path:
        try:
            storage = FileStorageService()
            storage.delete_file(user.avatar_path)
        except (OSError, ValueError):
            pass
        user.avatar_path = None
        await db.commit()
        await db.refresh(user)
    return _user_response(user)


@router.post("/me/signature/{kind}", response_model=UserResponse)
async def upload_signature(
    kind: str,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown signature kind: {kind}",
        )
    if not user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    if file.content_type not in ALLOWED_SIGNATURE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type {file.content_type} not allowed. "
                "Use PNG with transparent background."
            ),
        )

    content = await file.read()
    if len(content) > MAX_SIGNATURE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Signature must be under 500 KB.",
        )

    storage = FileStorageService()
    org_id = user.selected_org_id
    attr = _signature_path_attr(kind)
    relative_path = str(Path(str(org_id)) / "signatures" / f"{user.id}-{kind}.png")

    previous = getattr(user, attr)
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)

    setattr(user, attr, relative_path)
    await db.commit()
    await db.refresh(user)

    await log_audit(
        db,
        actor_id=user.id,
        action=("signature_replaced" if previous else "signature_created"),
        entity_type="user_signature",
        entity_id=user.id,
        changes={"kind": kind},
    )
    await db.commit()

    return _user_response(user)


@router.delete("/me/signature/{kind}", response_model=UserResponse)
async def delete_signature(
    kind: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown signature kind: {kind}",
        )
    attr = _signature_path_attr(kind)
    previous = getattr(user, attr)
    if previous:
        try:
            FileStorageService().delete_file(previous)
        except (OSError, ValueError):
            pass
        setattr(user, attr, None)
        await db.commit()
        await db.refresh(user)

        await log_audit(
            db,
            actor_id=user.id,
            action="signature_deleted",
            entity_type="user_signature",
            entity_id=user.id,
            changes={"kind": kind},
        )
        await db.commit()
    return _user_response(user)


async def _get_user_for_file(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve user from header auth or query-param token (for img/iframe)."""
    from app.core.security import decode_access_token

    payload = getattr(request.state, "token_payload", None)
    if payload is None and token:
        payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(User).where(User.id == payload.user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/avatars/{user_id}")
async def get_avatar(
    user_id: str,
    request: Request,
    current_user: User = Depends(_get_user_for_file),
    db: AsyncSession = Depends(get_db),
):
    """Serve a user's avatar. Requires org membership."""
    if not current_user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    # Look up the target user
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if target_user is None or not target_user.avatar_path:
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Verify requester is in the same org as the avatar owner
    result = await db.execute(
        select(OrganizationMember.id).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == current_user.selected_org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Avatar not found")

    storage = FileStorageService()
    try:
        full_path = storage.resolve_path(target_user.avatar_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Determine media type from extension
    ext = full_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/jpeg")

    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/signatures/{user_id}/{kind}")
async def get_signature(
    user_id: str,
    kind: str,
    request: Request,
    current_user: User = Depends(_get_user_for_file),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(status_code=404, detail="Signature not found")
    if not current_user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Signature not found")

    rel = getattr(target, _signature_path_attr(kind))
    if not rel:
        raise HTTPException(status_code=404, detail="Signature not found")

    same_org = (
        await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == current_user.selected_org_id,
            )
        )
    ).scalar_one_or_none()
    if same_org is None:
        raise HTTPException(status_code=404, detail="Signature not found")

    storage = FileStorageService()
    try:
        full_path = storage.resolve_path(rel)
    except ValueError:
        raise HTTPException(status_code=404, detail="Signature not found")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Signature not found")

    return FileResponse(full_path, media_type="image/png")


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
    if body.theme is not None:
        if body.theme not in ("lab-glass", "blueprint", "apothecary"):
            raise HTTPException(
                400,
                "theme must be lab-glass, blueprint, or apothecary",
            )
        prefs["theme"] = body.theme
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

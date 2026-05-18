import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_or_404, require_active_subscription
from app.core.security import generate_verification_token
from app.db.session import get_db
from app.models.execution import AuditLog
from app.models.iam import (
    _ALLOWED_ORG_ROLES,
    Invitation,
    InvitationStatus,
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    OrgRole,
    PermissionLevel,
    Team,
    TeamMember,
    TeamRole,
    User,
    has_org_role,
)
from app.models.science import Equipment
from app.schemas.iam import (
    InvitationCreate,
    InvitationResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrgMemberAdd,
    OrgMemberResponse,
    OrgMemberUpdate,
    PermissionGrant,
    PermissionResponse,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberResponse,
    TeamResponse,
    UserSearchResponse,
)
from app.schemas.science import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from app.services.billing import seat_limits
from app.services.core.permissions import check_permission

router = APIRouter()

_DEPRECATION_LOG = logging.getLogger("app.deprecation")


def _normalize_roles(input_roles: list[str] | None, raw_role: str | None) -> list[str]:
    """Server-side role normalization: ensure MEMBER, dedupe, validate.

    Raises HTTPException(400) on unknown values. Logs a deprecation warning
    when only the legacy `role` field is supplied.
    """
    if raw_role is not None and not input_roles:
        _DEPRECATION_LOG.warning(
            "OrganizationMember accepted deprecated single-role payload "
            "(role=%r). Switch to roles=[...] before next release.",
            raw_role,
        )
        input_roles = [raw_role]
    roles = list(input_roles or [])
    if OrgRole.MEMBER.value not in roles:
        roles.append(OrgRole.MEMBER.value)
    bad = [r for r in roles if r not in _ALLOWED_ORG_ROLES]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown role(s): {bad}. Allowed: " f"{sorted(_ALLOWED_ORG_ROLES)}"
            ),
        )
    seen: set[str] = set()
    out: list[str] = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# --- Helpers ---


async def _require_org_admin(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> OrganizationMember:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None or not has_org_role(membership, OrgRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org admin required",
        )
    return membership


async def _require_org_member(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> OrganizationMember:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not an org member",
        )
    return membership


# --- Organizations ---


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=201,
)
async def create_organization(
    body: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org = Organization(name=body.name)
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

    # Caller auto-becomes admin
    membership = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        roles=["ADMIN", "MEMBER"],
    )
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Organization)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.archived == False,
        )
    )
    return result.scalars().all()


@router.get("/organizations/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Must be an active member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    org = await get_or_404(db, Organization, org_id)
    return org


# --- Organization Members ---


@router.post(
    "/organizations/{org_id}/members",
    response_model=OrgMemberResponse,
)
async def add_org_member(
    org_id: UUID,
    body: OrgMemberAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    # Check target user exists
    result = await db.execute(select(User).where(User.id == body.user_id))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for existing membership (active or archived)
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == body.user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    existing = result.scalar_one_or_none()

    new_roles = _normalize_roles(body.roles, body.role)

    if existing is not None:
        if not existing.archived:
            raise HTTPException(status_code=409, detail="User is already a member")
        # Reactivate archived membership
        existing.archived = False
        existing.roles = new_roles
        membership = existing
    else:
        # Enforce max 3 admins per org
        if OrgRole.ADMIN.value in new_roles:
            admin_count = await db.execute(
                select(func.count()).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                    OrganizationMember.archived == False,
                )
            )
            if (admin_count.scalar() or 0) >= 3:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum of 3 admins per organization",
                )

        # Per-tier seat cap (F-0019a): refuse at cap; reactivation path above
        # is intentionally exempt since non-archived count doesn't change.
        org = await db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        await seat_limits.check_seat_capacity(db, org)

        membership = OrganizationMember(
            user_id=body.user_id,
            organization_id=org_id,
            roles=new_roles,
        )
        db.add(membership)

    # Set selected_org_id if the user doesn't have one
    if target_user.selected_org_id is None:
        target_user.selected_org_id = org_id

    await db.commit()
    await db.refresh(membership)
    return membership


@router.delete("/organizations/{org_id}/members/{user_id}")
async def remove_org_member(
    org_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Soft-delete: archive instead of deleting
    membership.archived = True
    await db.flush()

    # Cascade selected_org_id if this was the user's selected org
    target_user = await db.execute(select(User).where(User.id == user_id))
    target = target_user.scalar_one_or_none()
    if target is not None and target.selected_org_id == org_id:
        # Find the earliest remaining active membership
        fallback_result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.archived == False,
            )
            .order_by(OrganizationMember.created_at.asc())
            .limit(1)
        )
        fallback_org_id = fallback_result.scalar_one_or_none()
        target.selected_org_id = fallback_org_id  # None if no remaining orgs

    await db.commit()
    return {"ok": True}


@router.patch(
    "/organizations/{org_id}/members/{user_id}",
    response_model=OrgMemberResponse,
)
async def update_org_member_role(
    org_id: UUID,
    user_id: UUID,
    body: OrgMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    new_roles = _normalize_roles(body.roles, body.role)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Enforce max 3 admins (only when adding ADMIN to a member that didn't have it)
    becoming_admin = OrgRole.ADMIN.value in new_roles and not has_org_role(
        membership, OrgRole.ADMIN.value
    )
    if becoming_admin:
        admin_count = await db.execute(
            select(func.count()).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                OrganizationMember.archived == False,
            )
        )
        if (admin_count.scalar() or 0) >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum of 3 admins per organization",
            )

    # Enforce last-admin guard (only when removing ADMIN from a member that had it)
    losing_admin = OrgRole.ADMIN.value not in new_roles and has_org_role(
        membership, OrgRole.ADMIN.value
    )
    if losing_admin:
        admin_count_result = await db.execute(
            select(func.count()).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                OrganizationMember.archived == False,
            )
        )
        if (admin_count_result.scalar() or 0) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last admin from an organization",
            )

    membership.roles = new_roles
    await db.commit()
    await db.refresh(membership)
    return membership


@router.get(
    "/organizations/{org_id}/members",
    response_model=List[OrgMemberResponse],
)
async def list_org_members(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Must be active org member to view members
    await _require_org_member(db, user.id, org_id)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    memberships = result.scalars().all()

    # Enrich with user details
    enriched = []
    for m in memberships:
        user_result = await db.execute(select(User).where(User.id == m.user_id))
        u = user_result.scalar_one_or_none()
        enriched.append(
            OrgMemberResponse(
                id=m.id,
                user_id=m.user_id,
                organization_id=m.organization_id,
                roles=list(m.roles or []),
                email=u.email if u else None,
                full_name=u.full_name if u else None,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return enriched


# --- Users ---


@router.get("/users", response_model=List[UserSearchResponse])
async def search_users(
    email: str = Query("", min_length=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not email or len(email) < 3:
        return []

    # Get orgs the caller belongs to
    caller_org_ids = select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == user.id
    )

    # Only return users who share at least one org with the caller
    result = await db.execute(
        select(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            User.email.ilike(f"%{email}%"),
            OrganizationMember.organization_id.in_(caller_org_ids),
        )
        .distinct()
        .limit(10)
    )
    scoped_users = result.scalars().all()

    # Check if unscoped query would have returned more results
    unscoped_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(
            User.email.ilike(f"%{email}%"),
            User.id.notin_([u.id for u in scoped_users]),
        )
    )
    excluded_count = unscoped_result.scalar() or 0
    if excluded_count > 0:
        logger.warning(
            "Cross-org user search detected: user_id=%s email=%s "
            "search_term=%r excluded_count=%d",
            user.id,
            user.email,
            email,
            excluded_count,
        )

    return scoped_users


# --- Invitations ---


@router.post(
    "/organizations/{org_id}/invitations",
    response_model=InvitationResponse,
    status_code=201,
)
async def create_invitation(
    org_id: UUID,
    body: InvitationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Invite a user to the organization by email. Admin only."""
    await _require_org_admin(db, user.id, org_id)

    # Fetch org upfront (needed for email later, validates existence)
    org = await get_or_404(db, Organization, org_id)

    # Check if email is already an active member
    user_result = await db.execute(select(User).where(User.email == body.email))
    existing_user = user_result.scalar_one_or_none()

    if existing_user is not None:
        member_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.organization_id == org_id,
                OrganizationMember.archived == False,
            )
        )
        if member_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="User is already a member of this organization",
            )

    # Check for existing pending invitation
    pending_result = await db.execute(
        select(Invitation).where(
            Invitation.organization_id == org_id,
            Invitation.invited_email == body.email,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    if pending_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Active invitation already exists for this email",
        )

    token_str = generate_verification_token()
    invitation = Invitation(
        organization_id=org_id,
        invited_email=body.email,
        invited_user_id=existing_user.id if existing_user else None,
        role=body.role,
        invited_by=user.id,
        token=token_str,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Send invitation email (fire-and-forget)
    from app.services.core.email_service import send_invitation_email

    await send_invitation_email(
        to_email=body.email,
        org_name=org.name,
        inviter_name=user.full_name or user.email,
        token=token_str,
    )

    return invitation


@router.get(
    "/organizations/{org_id}/invitations",
    response_model=List[InvitationResponse],
)
async def list_org_invitations(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending invitations for an organization. Admin only."""
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(Invitation).where(
            Invitation.organization_id == org_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    return result.scalars().all()


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Revoke a pending invitation. Must be admin of the invitation's org."""
    result = await db.execute(select(Invitation).where(Invitation.id == invitation_id))
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    await _require_org_admin(db, user.id, invitation.organization_id)

    invitation.status = InvitationStatus.REVOKED
    await db.commit()
    return {"ok": True}


@router.get("/me/invitations", response_model=List[InvitationResponse])
async def list_my_invitations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending invitations for the current user."""
    result = await db.execute(
        select(Invitation).where(
            Invitation.invited_user_id == user.id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    return result.scalars().all()


@router.post("/invitations/{invitation_id}/decline")
async def decline_invitation(
    invitation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Decline a pending invitation."""
    result = await db.execute(select(Invitation).where(Invitation.id == invitation_id))
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Invitation is no longer pending")

    # Only the invited user can decline
    if invitation.invited_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to decline this invitation",
        )

    invitation.status = InvitationStatus.DECLINED
    await db.commit()
    return {"ok": True}


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_invitation(
    invitation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Resend a pending invitation with a new token and reset expiry."""
    result = await db.execute(select(Invitation).where(Invitation.id == invitation_id))
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Invitation is no longer pending")

    await _require_org_admin(db, user.id, invitation.organization_id)
    org = await get_or_404(db, Organization, invitation.organization_id)

    # Regenerate token and reset expiry
    invitation.token = generate_verification_token()
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.invitation_ttl_days
    )
    await db.commit()
    await db.refresh(invitation)

    # Resend email
    from app.services.core.email_service import send_invitation_email

    await send_invitation_email(
        to_email=invitation.invited_email,
        org_name=org.name,
        inviter_name=user.full_name or user.email,
        token=invitation.token,
    )

    return invitation


# --- Teams ---


@router.post(
    "/organizations/{org_id}/teams",
    response_model=TeamResponse,
    status_code=201,
)
async def create_team(
    org_id: UUID,
    body: TeamCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    team = Team(name=body.name, organization_id=org_id)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@router.get(
    "/organizations/{org_id}/teams",
    response_model=List[TeamResponse],
)
async def list_teams(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Must be active org member
    await _require_org_member(db, user.id, org_id)

    result = await db.execute(select(Team).where(Team.organization_id == org_id))
    return result.scalars().all()


@router.delete("/organizations/{org_id}/teams/{team_id}")
async def delete_team(
    org_id: UUID,
    team_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(Team).where(Team.id == team_id, Team.organization_id == org_id)
    )
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    await db.delete(team)
    await db.commit()
    return {"ok": True}


# --- Team Members ---


@router.post(
    "/teams/{team_id}/members",
    response_model=TeamMemberResponse,
)
async def add_team_member(
    team_id: UUID,
    body: TeamMemberAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    # Look up team to get org_id, then require org admin
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    await _require_org_admin(db, user.id, team.organization_id)

    # Check user not already in team
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == body.user_id,
            TeamMember.team_id == team_id,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User already in team")

    tm = TeamMember(
        user_id=body.user_id,
        team_id=team_id,
        role=TeamRole(body.role),
    )
    db.add(tm)
    await db.commit()
    await db.refresh(tm)
    return tm


@router.get(
    "/teams/{team_id}/members",
    response_model=List[TeamMemberResponse],
)
async def list_team_members(
    team_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Look up team to get org_id, check caller is org member
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == team.organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not an org member")

    result = await db.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    memberships = result.scalars().all()

    # Enrich with user details
    enriched = []
    for m in memberships:
        user_result = await db.execute(select(User).where(User.id == m.user_id))
        u = user_result.scalar_one_or_none()
        enriched.append(
            TeamMemberResponse(
                id=m.id,
                user_id=m.user_id,
                team_id=m.team_id,
                role=m.role,
                email=u.email if u else None,
                full_name=u.full_name if u else None,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return enriched


@router.delete("/teams/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    await _require_org_admin(db, user.id, team.organization_id)

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id,
        )
    )
    tm = result.scalar_one_or_none()
    if tm is None:
        raise HTTPException(status_code=404, detail="Team membership not found")

    await db.delete(tm)
    await db.commit()
    return {"ok": True}


# --- Permissions ---


@router.post(
    "/permissions",
    response_model=PermissionResponse,
    status_code=201,
)
async def grant_permission(
    body: PermissionGrant,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    # Caller must have ADMIN on the object
    obj_type = ObjectType(body.object_type)
    allowed = await check_permission(
        db,
        user.id,
        obj_type,
        body.object_id,
        PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(
            status_code=403, detail="ADMIN permission required on object"
        )

    # Check for existing permission
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.principal_type == body.principal_type,
            ObjectPermission.principal_id == body.principal_id,
            ObjectPermission.object_type == body.object_type,
            ObjectPermission.object_id == body.object_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.permission_level = body.permission_level
        await db.commit()
        await db.refresh(existing)
        return existing

    perm = ObjectPermission(
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        object_type=body.object_type,
        object_id=body.object_id,
        permission_level=body.permission_level,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    return perm


@router.delete("/permissions/{permission_id}")
async def revoke_permission(
    permission_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    result = await db.execute(
        select(ObjectPermission).where(ObjectPermission.id == permission_id)
    )
    perm = result.scalar_one_or_none()
    if perm is None:
        raise HTTPException(status_code=404, detail="Permission not found")

    # Caller must have ADMIN on the object
    obj_type = ObjectType(perm.object_type)
    allowed = await check_permission(
        db,
        user.id,
        obj_type,
        perm.object_id,
        PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="ADMIN permission required")

    await db.delete(perm)
    await db.commit()
    return {"ok": True}


@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    object_type: str = Query(...),
    object_id: UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.object_type == object_type,
            ObjectPermission.object_id == object_id,
        )
    )
    return result.scalars().all()


# --- Equipment ---


@router.get(
    "/organizations/{org_id}/equipment",
    response_model=List[EquipmentResponse],
)
async def list_equipment(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all equipment in an organization."""
    await _require_org_member(db, user.id, org_id)

    result = await db.execute(
        select(Equipment).where(Equipment.organization_id == org_id)
    )
    return result.scalars().all()


@router.post(
    "/organizations/{org_id}/equipment",
    response_model=EquipmentResponse,
    status_code=201,
)
async def create_equipment(
    org_id: UUID,
    body: EquipmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Create equipment in an organization. Any org member can create."""
    await _require_org_member(db, user.id, org_id)

    equipment = Equipment(
        organization_id=org_id,
        name=body.name,
        description=body.description,
        equipment_type=body.equipment_type,
        location=body.location,
    )
    db.add(equipment)
    await db.flush()

    # Log to audit trail
    audit = AuditLog(
        entity_type="equipment",
        entity_id=equipment.id,
        action="create",
        actor_id=user.id,
        changes={"name": body.name},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(equipment)
    return equipment


@router.put(
    "/equipment/{equipment_id}",
    response_model=EquipmentResponse,
)
async def update_equipment(
    equipment_id: UUID,
    body: EquipmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Update equipment. Any org member can update."""
    equipment = await get_or_404(db, Equipment, equipment_id)

    await _require_org_member(db, user.id, equipment.organization_id)

    changes = {}
    if body.name is not None:
        changes["name"] = body.name
        equipment.name = body.name
    if body.description is not None:
        changes["description"] = body.description
        equipment.description = body.description
    if body.equipment_type is not None:
        changes["equipment_type"] = body.equipment_type
        equipment.equipment_type = body.equipment_type
    if body.location is not None:
        changes["location"] = body.location
        equipment.location = body.location

    # Log to audit trail
    if changes:
        audit = AuditLog(
            entity_type="equipment",
            entity_id=equipment.id,
            action="update",
            actor_id=user.id,
            changes=changes,
        )
        db.add(audit)

    await db.commit()
    await db.refresh(equipment)
    return equipment


@router.delete("/equipment/{equipment_id}")
async def delete_equipment(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Delete equipment. Any org member can delete."""
    equipment = await get_or_404(db, Equipment, equipment_id)

    await _require_org_member(db, user.id, equipment.organization_id)

    # Log to audit trail before deleting
    audit = AuditLog(
        entity_type="equipment",
        entity_id=equipment.id,
        action="delete",
        actor_id=user.id,
        changes={"name": equipment.name},
    )
    db.add(audit)
    await db.delete(equipment)
    await db.commit()
    return {"ok": True}

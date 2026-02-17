from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import (
    Organization,
    OrganizationMember,
    Team,
    TeamMember,
    User,
    ObjectPermission,
    ObjectType,
    PermissionLevel,
    Role,
)
from app.schemas.iam import (
    OrganizationCreate,
    OrganizationResponse,
    OrgMemberAdd,
    OrgMemberUpdate,
    OrgMemberResponse,
    TeamCreate,
    TeamResponse,
    TeamMemberAdd,
    TeamMemberResponse,
    PermissionGrant,
    PermissionResponse,
    UserSearchResponse,
)
from app.services.permissions import check_permission

router = APIRouter()


# --- Helpers ---

async def _require_org_admin(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> OrganizationMember:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None or not membership.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org admin required",
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
):
    org = Organization(name=body.name)
    db.add(org)
    await db.flush()

    # Caller auto-becomes admin
    membership = OrganizationMember(
        user_id=user.id, organization_id=org.id, is_admin=True,
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
        .where(OrganizationMember.user_id == user.id)
    )
    return result.scalars().all()


@router.get(
    "/organizations/{org_id}", response_model=OrganizationResponse
)
async def get_organization(
    org_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Must be a member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
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
):
    await _require_org_admin(db, user.id, org_id)

    # Check target user exists
    result = await db.execute(
        select(User).where(User.id == body.user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check not already a member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == body.user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409, detail="User is already a member"
        )

    membership = OrganizationMember(
        user_id=body.user_id,
        organization_id=org_id,
        is_admin=body.is_admin,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


@router.delete("/organizations/{org_id}/members/{user_id}")
async def remove_org_member(
    org_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    await db.delete(membership)
    await db.commit()
    return {"ok": True}


@router.patch(
    "/organizations/{org_id}/members/{user_id}",
    response_model=OrgMemberResponse,
)
async def toggle_org_admin(
    org_id: UUID,
    user_id: UUID,
    body: OrgMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    membership.is_admin = body.is_admin
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
    # Must be org member to view members
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not an org member")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id
        )
    )
    memberships = result.scalars().all()

    # Enrich with user details
    enriched = []
    for m in memberships:
        user_result = await db.execute(
            select(User).where(User.id == m.user_id)
        )
        u = user_result.scalar_one_or_none()
        enriched.append(OrgMemberResponse(
            id=m.id,
            user_id=m.user_id,
            organization_id=m.organization_id,
            is_admin=m.is_admin,
            email=u.email if u else None,
            full_name=u.full_name if u else None,
            created_at=m.created_at,
            updated_at=m.updated_at,
        ))
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

    result = await db.execute(
        select(User).where(User.email.ilike(f"%{email}%")).limit(10)
    )
    return result.scalars().all()


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
    # Must be org member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not an org member")

    result = await db.execute(
        select(Team).where(Team.organization_id == org_id)
    )
    return result.scalars().all()


@router.delete("/organizations/{org_id}/teams/{team_id}")
async def delete_team(
    org_id: UUID,
    team_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin(db, user.id, org_id)

    result = await db.execute(
        select(Team).where(
            Team.id == team_id, Team.organization_id == org_id
        )
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
):
    # Look up team to get org_id, then require org admin
    result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
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
        raise HTTPException(
            status_code=409, detail="User already in team"
        )

    tm = TeamMember(
        user_id=body.user_id,
        team_id=team_id,
        role=Role(body.role),
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
    result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
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

    result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id)
    )
    memberships = result.scalars().all()

    # Enrich with user details
    enriched = []
    for m in memberships:
        user_result = await db.execute(
            select(User).where(User.id == m.user_id)
        )
        u = user_result.scalar_one_or_none()
        enriched.append(TeamMemberResponse(
            id=m.id,
            user_id=m.user_id,
            team_id=m.team_id,
            role=m.role,
            email=u.email if u else None,
            full_name=u.full_name if u else None,
            created_at=m.created_at,
            updated_at=m.updated_at,
        ))
    return enriched


@router.delete("/teams/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
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
        raise HTTPException(
            status_code=404, detail="Team membership not found"
        )

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
):
    # Caller must have ADMIN on the object
    obj_type = ObjectType(body.object_type)
    allowed = await check_permission(
        db, user.id, obj_type,
        body.object_id, PermissionLevel.ADMIN,
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
):
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.id == permission_id
        )
    )
    perm = result.scalar_one_or_none()
    if perm is None:
        raise HTTPException(status_code=404, detail="Permission not found")

    # Caller must have ADMIN on the object
    obj_type = ObjectType(perm.object_type)
    allowed = await check_permission(
        db, user.id, obj_type,
        perm.object_id, PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(
            status_code=403, detail="ADMIN permission required"
        )

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

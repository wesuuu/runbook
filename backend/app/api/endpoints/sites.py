from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_org_role
from app.models.iam import OrgRole, User
from app.schemas.sites import (ManagedSiteResponse, SiteArchiveRequest,
                               SiteCreate, SiteManagerGrantCreate,
                               SiteManagerGrantResponse, SiteResponse,
                               SiteUpdate)
from app.services.permissions.equipment import user_can_rename_site
from app.services.sites import crud, grants

router = APIRouter(tags=["sites"])


@router.get("/sites", response_model=list[SiteResponse])
async def list_sites_endpoint(
    include_archived: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud.list_sites(
        db, user.selected_org_id, include_archived=include_archived
    )


@router.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site_endpoint(
    site_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return site


@router.post("/sites", response_model=SiteResponse)
async def create_site_endpoint(
    payload: SiteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),  # ADMIN only (decision 5c-ii)
):
    return await crud.create_site(
        db, org_id=user.selected_org_id, payload=payload, actor_id=user.id
    )


@router.patch("/sites/{site_id}", response_model=SiteResponse)
async def update_site_endpoint(
    site_id: UUID,
    payload: SiteUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SITE_MANAGER with a grant on this site, or ADMIN. Decision 5c-ii."""
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    if not await user_can_rename_site(
        db, user_id=user.id, org_id=site.organization_id, site_id=site.id
    ):
        raise HTTPException(403)
    return await crud.update_site(db, site, payload=payload, actor_id=user.id)


@router.delete("/sites/{site_id}", response_model=SiteResponse)
async def archive_site_endpoint(
    site_id: UUID,
    body: SiteArchiveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),  # ADMIN only (decision 5c-ii)
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await crud.archive_site(
        db,
        site,
        default_move_to=body.default_move_to,
        overrides=body.overrides,
        reason=body.reason,
        actor_id=user.id,
    )


# ── Per-site SITE_MANAGER grants ───────────────────────────────────────
# Decision 4 + 5d-ii: ADMIN is the only role that grants and revokes.


@router.get(
    "/sites/{site_id}/managers",
    response_model=list[SiteManagerGrantResponse],
)
async def list_site_managers_endpoint(
    site_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await grants.list_grants_for_site(db, site_id)


@router.post(
    "/sites/{site_id}/managers",
    response_model=SiteManagerGrantResponse,
)
async def grant_site_manager_endpoint(
    site_id: UUID,
    payload: SiteManagerGrantCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await grants.grant_site_manager(
        db,
        site=site,
        user_id=payload.user_id,
        granted_by_id=user.id,
    )


@router.delete(
    "/sites/{site_id}/managers/{user_id}",
    status_code=204,
)
async def revoke_site_manager_endpoint(
    site_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    await grants.revoke_site_manager(
        db, site_id=site_id, user_id=user_id, actor_id=user.id
    )
    return Response(status_code=204)


@router.get(
    "/users/me/managed-sites",
    response_model=list[ManagedSiteResponse],
)
async def list_my_managed_sites_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Self-scoped alias for the caller's grants. Any authenticated org
    member can call this. Used by the frontend `canManageEquipmentLifecycle`
    helper (F-0088 decision 4) to know which sites the user can edit
    regulated metadata on."""
    rows = await grants.list_managed_sites_for_user(
        db, user.id, include_archived=False
    )
    # Filter to current org to keep cross-org isolation explicit, even
    # though grants are scoped to a single org via Site.organization_id.
    rows = [g for g in rows if g.site.organization_id == user.selected_org_id]
    return [{"grant_id": g.id, "site": g.site} for g in rows]


@router.get(
    "/users/{user_id}/managed-sites",
    response_model=list[ManagedSiteResponse],
)
async def list_managed_sites_endpoint(
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    """ADMIN-only because this surfaces another user's grant data. The
    inline `MemberSitesInlinePicker` in MemberRolesPicker (Task 31)
    consumes this when an ADMIN edits a member's roles."""
    rows = await grants.list_managed_sites_for_user(db, user_id, include_archived=False)
    return [{"grant_id": g.id, "site": g.site} for g in rows]

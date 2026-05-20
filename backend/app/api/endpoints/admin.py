"""Admin endpoints (F-0075).

Operations gated on org-admin of the caller's selected org. Today this
covers manual reload of the unit op library cache. As more system-level
operator actions accrete here, consider splitting per concern.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import OrganizationMember, OrgRole, User
from app.services.core.audit import log_audit
from app.services.protocols import library_registry

logger = logging.getLogger(__name__)
router = APIRouter()


async def _require_org_admin(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
) -> None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(403, "Org admin role required")


@router.post("/libraries/reload", status_code=200)
async def reload_libraries_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-read every registered LibrarySource. Returns the post-reload
    library inventory. Org-admin gated."""
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(400, "No organization selected")
    await _require_org_admin(db, user.id, org_id)

    await library_registry.reload_libraries()

    libs = library_registry.list_libraries()
    await log_audit(
        db,
        actor_id=user.id,
        action="UPDATE",
        entity_type="library_reload",
        entity_id=org_id,
        changes={"library_count": len(libs)},
    )
    await db.commit()

    return {
        "libraries": [
            {
                "slug": lib.slug,
                "name": lib.name,
                "version": lib.version,
                "op_count": len(lib.unit_ops),
            }
            for lib in libs
        ],
    }

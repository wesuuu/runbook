from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class SiteArchiveRequest(BaseModel):
    default_move_to: UUID
    overrides: dict[UUID, UUID] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)


class SiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    is_default: bool
    archived_at: datetime | None
    archived_by_id: UUID | None
    archive_reason: str | None
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SiteManagerGrantCreate(BaseModel):
    """Body for POST /sites/{site_id}/managers — single user_id per call.

    Bulk grant flows on the frontend (`MemberSitesInlinePicker`, the site
    detail "+ Add manager" picker) iterate this endpoint client-side; the
    backend stays one-grant-per-row to keep audit entries 1:1 with grants.
    """

    user_id: UUID


class SiteManagerGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    site_id: UUID
    user_id: UUID
    granted_by_id: UUID | None
    created_at: datetime


class ManagedSiteResponse(BaseModel):
    """Returned by GET /users/{user_id}/managed-sites — joins grant + site.

    Frontend `MemberSitesInlinePicker` needs both the grant id (for revoke)
    and the site name (for display) in one shot; an embedded SiteResponse
    keeps the picker query off the sites endpoint.
    """

    model_config = ConfigDict(from_attributes=True)

    grant_id: UUID
    site: SiteResponse

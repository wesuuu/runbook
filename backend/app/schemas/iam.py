from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.slug import slugify

# Hierarchy used to derive the legacy single `role` from the `roles` list.
# Highest-ranked role wins. ADMIN > BILLING > PROTOCOL_APPROVER > MEMBER.
_LEGACY_ROLE_RANK = {
    "ADMIN": 4,
    "BILLING": 3,
    "PROTOCOL_APPROVER": 2,
    "SITE_MANAGER": 2,
    "MEMBER": 1,
}


def _legacy_role_from_roles(roles: list[str]) -> str:
    if not roles:
        return "MEMBER"
    return max(roles, key=lambda r: _LEGACY_ROLE_RANK.get(r, 0))


class OrganizationCreate(BaseModel):
    name: str


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    subscription_tier: str = "essentials"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str:
        """URL slug derived from the org name. Not an identifier — two
        orgs may share a slug; the session JWT identifies the real org."""
        return slugify(self.name)


class OrgMemberAdd(BaseModel):
    user_id: UUID
    roles: Optional[List[str]] = None
    role: Optional[str] = None  # deprecated, accepted for back-compat


class OrgMemberUpdate(BaseModel):
    roles: Optional[List[str]] = None
    role: Optional[str] = None  # deprecated, accepted for back-compat


class OrgMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    roles: List[str]
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def role(self) -> str:
        # Legacy field: derive a single role from the `roles` list for back-compat.
        return _legacy_role_from_roles(list(self.roles or []))


class TeamCreate(BaseModel):
    name: str


class TeamResponse(BaseModel):
    id: UUID
    name: str
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamMemberAdd(BaseModel):
    user_id: UUID
    role: str = "MEMBER"


class TeamMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    team_id: UUID
    role: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSearchResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class InvitationCreate(BaseModel):
    email: str
    role: str = "MEMBER"


class InvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    invited_email: str
    invited_user_id: Optional[UUID] = None
    role: str
    invited_by: UUID
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PermissionGrant(BaseModel):
    principal_type: str  # "USER" or "TEAM"
    principal_id: UUID
    object_type: str  # "PROJECT", "PROTOCOL", "EXPERIMENT"
    object_id: UUID
    permission_level: str  # "VIEW", "EDIT", "ADMIN"


class PermissionResponse(BaseModel):
    id: UUID
    principal_type: str
    principal_id: UUID
    object_type: str
    object_id: UUID
    permission_level: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

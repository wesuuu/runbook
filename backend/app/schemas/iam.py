from uuid import UUID
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class OrganizationCreate(BaseModel):
    name: str


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrgMemberAdd(BaseModel):
    user_id: UUID
    role: str = "MEMBER"  # ADMIN, BILLING, MEMBER


class OrgMemberUpdate(BaseModel):
    role: str  # ADMIN, BILLING, MEMBER


class OrgMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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

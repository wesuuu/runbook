from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: dict[str, Any] = {}
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    job_title: Optional[str] = None


class PreferencesUpdate(BaseModel):
    font_size: Optional[str] = None    # "small" | "medium" | "large"
    density: Optional[str] = None      # "compact" | "comfortable"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

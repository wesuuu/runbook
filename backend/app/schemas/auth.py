from uuid import UUID
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict


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
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

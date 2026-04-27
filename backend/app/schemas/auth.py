from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.legal.service import get_current_version


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


def compute_tos_current(user: Any) -> bool:
    """Return True if the user is considered current on ToS acceptance.

    True when ANY of:
      * the deployment-level gate is disabled, OR
      * the user's selected organization has legal_terms_overridden=True, OR
      * the user's tos_version equals the current version.

    Note: reads `selected_organization` via `__dict__` to avoid
    triggering a SQLAlchemy lazy load in async contexts (which would
    raise MissingGreenlet). Callers that want the org-override branch
    evaluated must eager-load `User.selected_organization` (e.g., via
    `selectinload` in `get_current_user`). When not loaded, the helper
    falls back to comparing `tos_version` against the current version.
    """
    if not settings.legal_gate_enabled:
        return True
    # __dict__ works for both SimpleNamespace (tests) and SA ORM
    # instances. For ORM instances the key is only present when the
    # relationship was eager-loaded, so this never triggers a lazy load.
    org = None
    user_dict = getattr(user, "__dict__", None)
    if user_dict is not None:
        org = user_dict.get("selected_organization")
    if org is not None and getattr(org, "legal_terms_overridden", False):
        return True
    return user.tos_version == get_current_version()


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: dict[str, Any] = {}
    is_active: bool
    email_verified: bool
    tos_accepted_at: Optional[datetime] = None
    tos_version: Optional[str] = None
    tos_current: bool

    model_config = ConfigDict(from_attributes=True)


class VerificationTokenResponse(BaseModel):
    verification_token: str
    message: str


class ResendVerificationResponse(BaseModel):
    message: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    job_title: Optional[str] = None


class PreferencesUpdate(BaseModel):
    font_size: Optional[str] = None    # "small" | "medium" | "large"
    density: Optional[str] = None      # "compact" | "comfortable"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class SwitchOrgRequest(BaseModel):
    org_id: UUID

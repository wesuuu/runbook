import uuid
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class SubscriptionTier(str, Enum):
    ESSENTIALS = "essentials"
    PRO = "pro"
    ENTERPRISE = "enterprise"


TIER_RANK = {
    SubscriptionTier.ESSENTIALS: 0,
    SubscriptionTier.PRO: 1,
    SubscriptionTier.ENTERPRISE: 2,
}


class OrgRole(str, Enum):
    ADMIN = "ADMIN"
    BILLING = "BILLING"
    MEMBER = "MEMBER"
    PROTOCOL_APPROVER = "PROTOCOL_APPROVER"
    SITE_MANAGER = "SITE_MANAGER"


_ALLOWED_ORG_ROLES = frozenset(r.value for r in OrgRole)


class TeamRole(str, Enum):
    LEAD = "LEAD"
    MEMBER = "MEMBER"


class InvitationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PrincipalType(str, Enum):
    USER = "USER"
    TEAM = "TEAM"


class ObjectType(str, Enum):
    PROJECT = "PROJECT"
    PROTOCOL = "PROTOCOL"
    RUN = "RUN"
    DOCUMENT = "DOCUMENT"


class PermissionLevel(str, Enum):
    VIEW = "VIEW"
    EDIT = "EDIT"
    APPROVE = "APPROVE"
    ADMIN = "ADMIN"


# Ordered for comparison
PERMISSION_RANK = {
    PermissionLevel.VIEW: 1,
    PermissionLevel.EDIT: 2,
    PermissionLevel.APPROVE: 3,
    PermissionLevel.ADMIN: 4,
}


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String, nullable=False)
    subscription_tier: Mapped[str] = mapped_column(
        String, nullable=False, server_default=SubscriptionTier.ESSENTIALS.value
    )
    default_sop_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_org_sop_tpl"),
        nullable=True,
    )
    default_batch_record_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_org_br_tpl"),
        nullable=True,
    )

    # Stripe billing (added F-0019a — nullable; existing orgs default to null)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    has_payment_method: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    legal_terms_overridden: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    # Relationships
    teams: Mapped[List["Team"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[List["Project"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    members: Mapped[List["OrganizationMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Team(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="teams")
    members: Mapped[List["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "oauth_provider", "oauth_subject", name="uq_oauth_provider_subject"
        ),
    )

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String)
    job_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    signature_initials_path: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    signature_full_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    tour_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    oauth_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oauth_email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    tos_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selected_org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    # Relationships
    team_memberships: Mapped[List["TeamMember"]] = relationship(back_populates="user")
    org_memberships: Mapped[List["OrganizationMember"]] = relationship(
        back_populates="user"
    )
    selected_organization: Mapped[Optional["Organization"]] = relationship(
        foreign_keys=[selected_org_id]
    )


class TeamMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_members"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default=TeamRole.MEMBER, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="team_memberships")
    team: Mapped["Team"] = relationship(back_populates="members")


class OrganizationMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_org_member"),
        CheckConstraint(
            "roles <@ ARRAY['ADMIN','BILLING','MEMBER',"
            "'PROTOCOL_APPROVER','SITE_MANAGER']::varchar[]",
            name="ck_org_member_roles",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    roles: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("ARRAY['MEMBER']::varchar[]"),
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship(back_populates="members")


def has_org_role(membership: "OrganizationMember", role: str) -> bool:
    """True if the membership holds the given role."""
    return role in (membership.roles or [])


def has_any_org_role(membership: "OrganizationMember", roles: List[str]) -> bool:
    """True if the membership holds any of the given roles."""
    member_roles = set(membership.roles or [])
    return any(r in member_roles for r in roles)


class ObjectPermission(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "object_permissions"
    __table_args__ = (
        UniqueConstraint(
            "principal_type",
            "principal_id",
            "object_type",
            "object_id",
            "permission_level",
            name="uq_object_permission",
        ),
        Index("ix_objperm_object", "object_type", "object_id"),
        Index("ix_objperm_principal", "principal_type", "principal_id"),
    )

    principal_type: Mapped[str] = mapped_column(String, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    permission_level: Mapped[str] = mapped_column(String, nullable=False)


class Invitation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "invitations"
    __table_args__ = (
        Index(
            "ix_pending_invitation",
            "organization_id",
            "invited_email",
            unique=True,
            postgresql_where="status = 'PENDING'",
        ),
        Index("ix_invitation_token", "token", unique=True),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_email: Mapped[str] = mapped_column(String, nullable=False)
    invited_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String, default=OrgRole.MEMBER, nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=InvitationStatus.PENDING,
        server_default="PENDING",
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(foreign_keys=[organization_id])
    invited_user: Mapped[Optional["User"]] = relationship(
        foreign_keys=[invited_user_id]
    )
    inviter: Mapped["User"] = relationship(foreign_keys=[invited_by])


class VerificationToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

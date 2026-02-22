import uuid
from enum import Enum
from typing import List, Optional

from sqlalchemy import String, ForeignKey, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class Role(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class PrincipalType(str, Enum):
    USER = "USER"
    TEAM = "TEAM"


class ObjectType(str, Enum):
    PROJECT = "PROJECT"
    PROTOCOL = "PROTOCOL"
    RUN = "RUN"


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
    organization: Mapped["Organization"] = relationship(
        back_populates="teams"
    )
    members: Mapped[List["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    team_memberships: Mapped[List["TeamMember"]] = relationship(
        back_populates="user"
    )
    org_memberships: Mapped[List["OrganizationMember"]] = relationship(
        back_populates="user"
    )


class TeamMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        String, default=Role.MEMBER, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="team_memberships")
    team: Mapped["Team"] = relationship(back_populates="members")


class OrganizationMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", name="uq_org_member"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship(
        back_populates="members"
    )


class ObjectPermission(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "object_permissions"
    __table_args__ = (
        UniqueConstraint(
            "principal_type", "principal_id",
            "object_type", "object_id",
            name="uq_object_permission",
        ),
        Index(
            "ix_objperm_object", "object_type", "object_id"
        ),
        Index(
            "ix_objperm_principal", "principal_type", "principal_id"
        ),
    )

    principal_type: Mapped[str] = mapped_column(String, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    permission_level: Mapped[str] = mapped_column(String, nullable=False)

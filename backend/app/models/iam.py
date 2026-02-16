import uuid
from enum import Enum
from typing import List, Optional
from sqlalchemy import String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin

class Role(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"

class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String, nullable=False)
    
    # Relationships
    teams: Mapped[List["Team"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[List["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")

class Team(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="teams")
    members: Mapped[List["TeamMember"]] = relationship(back_populates="team", cascade="all, delete-orphan")

class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    team_memberships: Mapped[List["TeamMember"]] = relationship(back_populates="user")

class TeamMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_members"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    role: Mapped[Role] = mapped_column(String, default=Role.MEMBER, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="team_memberships")
    team: Mapped["Team"] = relationship(back_populates="members")

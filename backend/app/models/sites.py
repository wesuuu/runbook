"""Site domain models (TD-0083): Site, SiteManagerGrant."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class Site(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = (
        Index("ix_sites_org", "organization_id"),
        Index(
            "uq_sites_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "uq_sites_org_is_default",
            "organization_id",
            unique=True,
            postgresql_where=text("is_default = true AND archived_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    equipment = relationship("Equipment", back_populates="site", lazy="select")


class SiteManagerGrant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "site_manager_grants"
    __table_args__ = (
        Index("ix_site_manager_grants_site", "site_id"),
        Index("ix_site_manager_grants_user", "user_id"),
        Index("ix_site_manager_grants_org", "organization_id"),
        Index(
            "uq_site_manager_grants_site_user",
            "site_id",
            "user_id",
            unique=True,
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    site = relationship("Site", lazy="joined")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    granted_by = relationship("User", foreign_keys=[granted_by_id], lazy="select")

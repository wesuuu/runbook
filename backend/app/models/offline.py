"""Models for offline field mode sessions and token revocation."""

import uuid
from typing import Optional

from sqlalchemy import String, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class RevokedOfflineToken(Base, UUIDMixin, TimestampMixin):
    """Blacklist for revoked offline JWT tokens, keyed by jti claim."""

    __tablename__ = "revoked_offline_tokens"

    jti: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, nullable=False,
        comment="JWT ID (jti) claim from the offline token",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=True,
    )
    revoked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
        comment="Admin user who revoked the token",
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id])
    revoker = relationship("User", foreign_keys=[revoked_by])

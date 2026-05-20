"""Sign-off domain models (TD-0083): GlpRole, GlpSignoffAction, GlpSignoffRequestStatus, GlpSignoff, GlpSignoffRequest."""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.iam import User
    from app.models.protocols import Protocol
    from app.models.runs import Run


class GlpRole(str, Enum):
    """21 CFR Part 58 roles used across protocol approval and run sign-off."""

    SPONSOR = "SPONSOR"  # §58.10, §58.120(a)
    STUDY_DIRECTOR = "STUDY_DIRECTOR"  # §58.33
    QAU = "QAU"  # §58.35
    OPERATOR = "OPERATOR"  # §58.29


class GlpSignoffAction(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUESTED_CHANGES = "REQUESTED_CHANGES"


class GlpSignoffRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class GlpSignoff(Base, UUIDMixin, TimestampMixin):
    """Unified GLP signature event for both protocol approvals
    (pre-execution) and run sign-offs (during/post-execution).
    Partition by FK: exactly one of protocol_id/run_id is set.

    This model is the single source of truth for signature events after
    F-0087 Task 27 retired the legacy protocol-approval events table.
    """

    __tablename__ = "glp_signoffs"
    __table_args__ = (
        CheckConstraint(
            "(protocol_id IS NOT NULL AND run_id IS NULL) OR "
            "(protocol_id IS NULL AND run_id IS NOT NULL)",
            name="ck_glp_signoff_scope",
        ),
        CheckConstraint(
            "role IN ('SPONSOR','STUDY_DIRECTOR','QAU','OPERATOR')",
            name="ck_glp_signoff_role",
        ),
        CheckConstraint(
            "action IN ('APPROVED','REJECTED','REQUESTED_CHANGES')",
            name="ck_glp_signoff_action",
        ),
        CheckConstraint(
            "(protocol_id IS NULL) OR " "(role IN ('SPONSOR','STUDY_DIRECTOR','QAU'))",
            name="ck_protocol_signoff_roles",
        ),
        CheckConstraint(
            "(run_id IS NULL) OR " "(role IN ('OPERATOR','STUDY_DIRECTOR','QAU'))",
            name="ck_run_signoff_roles",
        ),
        CheckConstraint(
            "(action != 'APPROVED') OR "
            "(attestation IS NOT NULL AND signature_image_path IS NOT NULL)",
            name="ck_approved_requires_attestation",
        ),
        Index(
            "ux_glp_signoff_active_protocol",
            "protocol_id",
            "role",
            unique=True,
            postgresql_where=text(
                "protocol_id IS NOT NULL AND action='APPROVED' "
                "AND invalidated_at IS NULL"
            ),
        ),
        Index(
            "ux_glp_signoff_active_run",
            "run_id",
            "role",
            unique=True,
            postgresql_where=text(
                "run_id IS NOT NULL AND action='APPROVED' " "AND invalidated_at IS NULL"
            ),
        ),
    )

    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )

    role: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)

    signer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    attestation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    signoff_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "glp_signoff_requests.id",
            use_alter=True,
            name="fk_glp_signoff_request",
        ),
        nullable=True,
    )

    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invalidated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Grilling decision #15: distinguish edit-invalidation vs reopen-supersession.
    # Both set invalidated_at; only reopen sets this FK to the audit event row.
    superseded_by_reopen_audit_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "audit_logs.id",
            use_alter=True,
            name="fk_glp_signoff_superseded_by",
        ),
        nullable=True,
    )

    protocol: Mapped[Optional["Protocol"]] = relationship(
        "Protocol", foreign_keys=[protocol_id]
    )
    run: Mapped[Optional["Run"]] = relationship("Run", foreign_keys=[run_id])
    signer: Mapped["User"] = relationship(
        "app.models.iam.User", foreign_keys=[signer_id]
    )
    invalidated_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[invalidated_by_id]
    )


class GlpSignoffRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "glp_signoff_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','APPROVED','REJECTED','WITHDRAWN')",
            name="ck_proto_appr_req_status",
        ),
        Index(
            "ix_proto_appr_req_open_unique",
            "protocol_id",
            "requested_user_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    requested_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="OPEN", server_default="OPEN", nullable=False
    )
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="approval_requests")
    requested_user: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_user_id]
    )
    requested_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_by_id]
    )
    fulfilled_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[fulfilled_by_id]
    )

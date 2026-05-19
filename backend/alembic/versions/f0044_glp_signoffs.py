"""F-0087 glp signoffs unified table

Revision ID: f0044_glp_signoffs
Revises: f0043
Create Date: 2026-05-18

Creates the unified glp_signoffs table (replaces ProtocolApprovalEvent for
GLP sign-off workflows), renames protocol_approval_requests to
glp_signoff_requests, adds GLP run lifecycle columns (started_at,
completed_at, outcome, outcome_notes) and equipment calibration columns
(serial_number, last_calibration_date, next_calibration_date,
calibration_certificate_path).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f0044_glp_signoffs"
down_revision: Union[str, Sequence[str], None] = "f0088_sites_equipment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Rename protocol_approval_requests -> glp_signoff_requests
    #    The ORM model already uses __tablename__ = "glp_signoff_requests".
    #    The existing partial unique index references the old table name;
    #    drop it, rename, recreate.
    # ------------------------------------------------------------------
    op.drop_index(
        "ix_proto_appr_req_open_unique",
        table_name="protocol_approval_requests",
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.rename_table("protocol_approval_requests", "glp_signoff_requests")
    op.create_index(
        "ix_proto_appr_req_open_unique",
        "glp_signoff_requests",
        ["protocol_id", "requested_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    # ------------------------------------------------------------------
    # 2. Create glp_signoffs table (16 payload columns + UUIDMixin +
    #    TimestampMixin = 18 total)
    #    superseded_by_reopen_audit_event_id uses use_alter=True
    #    (circular-dependency guard per grilling decision #15).
    # ------------------------------------------------------------------
    op.create_table(
        "glp_signoffs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Scope FK — exactly one of protocol_id / run_id is non-NULL
        sa.Column("protocol_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        # Core sign-off fields
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("signer_id", sa.UUID(), nullable=False),
        sa.Column("attestation", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signature_image_path", sa.String(), nullable=True),
        # Optional back-link to the request that triggered this sign-off
        sa.Column("signoff_request_id", sa.UUID(), nullable=True),
        # Invalidation fields (edit-based or reopen-based)
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
        sa.Column("invalidated_by_id", sa.UUID(), nullable=True),
        # Grilling decision #15 — reopen audit event FK (use_alter circular guard)
        sa.Column("superseded_by_reopen_audit_event_id", sa.UUID(), nullable=True),
        # ---- CHECK constraints ----
        sa.CheckConstraint(
            "(protocol_id IS NOT NULL AND run_id IS NULL) OR "
            "(protocol_id IS NULL AND run_id IS NOT NULL)",
            name="ck_glp_signoff_scope",
        ),
        sa.CheckConstraint(
            "role IN ('SPONSOR','STUDY_DIRECTOR','QAU','OPERATOR')",
            name="ck_glp_signoff_role",
        ),
        sa.CheckConstraint(
            "action IN ('APPROVED','REJECTED','REQUESTED_CHANGES')",
            name="ck_glp_signoff_action",
        ),
        sa.CheckConstraint(
            "(protocol_id IS NULL) OR (role IN ('SPONSOR','STUDY_DIRECTOR','QAU'))",
            name="ck_protocol_signoff_roles",
        ),
        sa.CheckConstraint(
            "(run_id IS NULL) OR (role IN ('OPERATOR','STUDY_DIRECTOR','QAU'))",
            name="ck_run_signoff_roles",
        ),
        # ---- FK constraints ----
        sa.ForeignKeyConstraint(
            ["protocol_id"],
            ["protocols.id"],
            ondelete="CASCADE",
            name="fk_glp_signoff_protocol",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            ondelete="CASCADE",
            name="fk_glp_signoff_run",
        ),
        sa.ForeignKeyConstraint(
            ["signer_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_glp_signoff_signer",
        ),
        sa.ForeignKeyConstraint(
            ["invalidated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_glp_signoff_invalidated_by",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # signoff_request_id FK — deferred via use_alter to avoid ordering issues
    op.create_foreign_key(
        "fk_glp_signoff_request",
        "glp_signoffs",
        "glp_signoff_requests",
        ["signoff_request_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    # superseded_by_reopen_audit_event_id FK — use_alter (circular guard #15)
    op.create_foreign_key(
        "fk_glp_signoff_superseded_by",
        "glp_signoffs",
        "audit_logs",
        ["superseded_by_reopen_audit_event_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    # ------------------------------------------------------------------
    # 3. Partial unique indexes
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX ux_glp_signoff_active_protocol
        ON glp_signoffs (protocol_id, role)
        WHERE protocol_id IS NOT NULL
          AND action = 'APPROVED'
          AND invalidated_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_glp_signoff_active_run
        ON glp_signoffs (run_id, role)
        WHERE run_id IS NOT NULL
          AND action = 'APPROVED'
          AND invalidated_at IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 5. Data migration: seed glp_signoffs from protocol_approval_events.
    #    protocol_approval_events columns: id, created_at, updated_at,
    #    protocol_id, protocol_version_id, actor_id, action, comment,
    #    signature_statement.
    #    Map action: 'APPROVED' -> 'APPROVED', others -> skip (only
    #    APPROVED events make sense as completed sign-offs; SUBMITTED /
    #    REJECTED / REVERTED have no direct glp_signoffs equivalent yet).
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO glp_signoffs (
            id,
            created_at,
            updated_at,
            protocol_id,
            run_id,
            role,
            action,
            signer_id,
            attestation,
            signed_at,
            signature_image_path,
            signoff_request_id,
            invalidated_at,
            invalidated_reason,
            invalidated_by_id,
            superseded_by_reopen_audit_event_id
        )
        SELECT
            pae.id,
            pae.created_at,
            pae.updated_at,
            pae.protocol_id,
            NULL::uuid,                  -- run_id: protocol approvals have no run
            'STUDY_DIRECTOR'::varchar,   -- role: best-fit default for legacy events
            pae.action,
            pae.actor_id,               -- signer_id mapped from actor_id
            pae.signature_statement,    -- attestation mapped from signature_statement
            pae.created_at,             -- signed_at: use created_at as proxy
            NULL::varchar,              -- signature_image_path: not captured in old model
            NULL::uuid,                 -- signoff_request_id: no direct mapping
            NULL::timestamptz,          -- invalidated_at
            NULL::text,                 -- invalidated_reason
            NULL::uuid,                 -- invalidated_by_id
            NULL::uuid                  -- superseded_by_reopen_audit_event_id
        FROM protocol_approval_events pae
        WHERE pae.action = 'APPROVED'
          AND pae.actor_id IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # 6. NOT VALID check constraint for approved-requires-attestation.
    #    Added AFTER data migration so migrated rows (which may lack
    #    signature_image_path) are not rejected. NOT VALID skips the
    #    table scan but still enforces on new inserts going forward.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE glp_signoffs
        ADD CONSTRAINT ck_approved_requires_attestation
        CHECK (
            (action != 'APPROVED') OR
            (attestation IS NOT NULL AND signature_image_path IS NOT NULL)
        )
        NOT VALID
        """
    )

    # ------------------------------------------------------------------
    # 8. Add GLP run lifecycle columns to runs table
    # ------------------------------------------------------------------
    op.add_column(
        "runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("outcome", sa.String(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("outcome_notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_runs_outcome", "runs", ["outcome"])

    # ------------------------------------------------------------------
    # 9. Add equipment.calibration_certificate_path
    # serial_number, last_calibration_date, next_calibration_date already
    # added by f0088_sites_equipment (renamed from next_calibration_due).
    # ------------------------------------------------------------------
    op.add_column(
        "equipment",
        sa.Column("calibration_certificate_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    # Equipment calibration columns
    op.drop_column("equipment", "calibration_certificate_path")

    # Run GLP columns
    op.drop_index("ix_runs_outcome", table_name="runs")
    op.drop_column("runs", "outcome_notes")
    op.drop_column("runs", "outcome")
    op.drop_column("runs", "completed_at")
    op.drop_column("runs", "started_at")

    # glp_signoffs indexes + table
    op.execute("DROP INDEX IF EXISTS ux_glp_signoff_active_run")
    op.execute("DROP INDEX IF EXISTS ux_glp_signoff_active_protocol")
    op.drop_constraint(
        "fk_glp_signoff_superseded_by", "glp_signoffs", type_="foreignkey"
    )
    op.drop_constraint("fk_glp_signoff_request", "glp_signoffs", type_="foreignkey")
    op.drop_table("glp_signoffs")

    # Rename glp_signoff_requests back to protocol_approval_requests
    op.drop_index(
        "ix_proto_appr_req_open_unique",
        table_name="glp_signoff_requests",
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.rename_table("glp_signoff_requests", "protocol_approval_requests")
    op.create_index(
        "ix_proto_appr_req_open_unique",
        "protocol_approval_requests",
        ["protocol_id", "requested_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

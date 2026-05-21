"""f0080 run sign-off requests: extend glp_signoff_requests for runs

Revision ID: f0080_run_signoff_requests
Revises: f0087_qau_org_role
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "f0080_run_signoff_requests"
down_revision = "f0087_qau_org_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. New columns on glp_signoff_requests.
    op.add_column(
        "glp_signoff_requests",
        sa.Column(
            "run_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=True,
        ),
    )
    op.add_column(
        "glp_signoff_requests", sa.Column("role", sa.String(), nullable=True),
    )
    op.alter_column("glp_signoff_requests", "protocol_id", nullable=True)

    # 2. Status CHECK — add CANCELLED. Drop-if-exists keeps re-runs idempotent.
    op.execute(
        "ALTER TABLE glp_signoff_requests "
        "DROP CONSTRAINT IF EXISTS ck_proto_appr_req_status"
    )
    op.execute(
        "ALTER TABLE glp_signoff_requests ADD CONSTRAINT ck_proto_appr_req_status "
        "CHECK (status IN ('OPEN','APPROVED','REJECTED','WITHDRAWN','CANCELLED'))"
    )

    # 3. XOR target constraint.
    op.execute(
        "ALTER TABLE glp_signoff_requests "
        "DROP CONSTRAINT IF EXISTS ck_signoff_request_target"
    )
    op.execute(
        "ALTER TABLE glp_signoff_requests ADD CONSTRAINT ck_signoff_request_target "
        "CHECK ((protocol_id IS NOT NULL AND run_id IS NULL) OR "
        "(protocol_id IS NULL AND run_id IS NOT NULL))"
    )

    # 4. One OPEN request per (run_id, role).
    op.execute(
        "CREATE UNIQUE INDEX ux_signoff_request_active_run "
        "ON glp_signoff_requests (run_id, role) WHERE status = 'OPEN'"
    )

    # 5. Run reviewer columns.
    op.add_column(
        "runs",
        sa.Column(
            "study_director_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "qau_reviewer_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "qau_reviewer_id")
    op.drop_column("runs", "study_director_id")
    op.execute("DROP INDEX IF EXISTS ux_signoff_request_active_run")
    op.execute(
        "ALTER TABLE glp_signoff_requests "
        "DROP CONSTRAINT IF EXISTS ck_signoff_request_target"
    )
    op.execute(
        "ALTER TABLE glp_signoff_requests "
        "DROP CONSTRAINT IF EXISTS ck_proto_appr_req_status"
    )
    op.execute(
        "ALTER TABLE glp_signoff_requests ADD CONSTRAINT ck_proto_appr_req_status "
        "CHECK (status IN ('OPEN','APPROVED','REJECTED','WITHDRAWN'))"
    )
    op.drop_column("glp_signoff_requests", "role")
    op.drop_column("glp_signoff_requests", "run_id")
    op.alter_column("glp_signoff_requests", "protocol_id", nullable=False)

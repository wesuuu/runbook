"""phases 4-7 experiments

Adds conclusion lock columns to experiments, key_result triple to runs, and
backfills existing all-terminal experiments as locked so they don't silently
demote to AWAITING_CONCLUSION post-deploy.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '92ca639b721b'
down_revision: Union[str, Sequence[str], None] = '110e8c13b63c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("conclusion", sa.Text(), nullable=True),
    )
    op.add_column(
        "experiments",
        sa.Column("conclusion_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "experiments",
        sa.Column(
            "conclusion_locked_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "experiments",
        sa.Column("conclusion_locked_by_name", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_experiments_conclusion_locked_by_id",
        "experiments",
        "users",
        ["conclusion_locked_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "runs",
        sa.Column("key_result_label", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("key_result_value", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("key_result_unit", sa.String(length=32), nullable=True),
    )

    # NOT VALID skips the historical scan; VALIDATE runs without
    # ShareRowExclusiveLock in a separate autocommit transaction.
    op.execute(
        "ALTER TABLE runs ADD CONSTRAINT ck_runs_key_result_paired "
        "CHECK ((key_result_label IS NULL) = (key_result_value IS NULL)) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE runs VALIDATE CONSTRAINT ck_runs_key_result_paired")

    # NaN/Inf defense at the database layer: even though Pydantic rejects
    # NaN/Inf at the API, a raw-SQL admin tool or future bulk-import path
    # could write 'NaN' into Numeric. Reject it here.
    op.execute(
        "ALTER TABLE runs ADD CONSTRAINT ck_runs_key_result_value_finite "
        "CHECK (key_result_value IS NULL OR key_result_value::text NOT IN ('NaN', 'Infinity', '-Infinity')) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE runs VALIDATE CONSTRAINT ck_runs_key_result_value_finite")

    # Backfill: lock any experiment that today reads as "complete" (has runs,
    # no open runs) so the AWAITING_CONCLUSION migration is invisible to users
    # who already perceive these as done.
    #
    # Policy decisions resulting from review panel:
    #   - Leave `conclusion` NULL (do NOT write a sentinel string). The
    #     experiment PDF will render "—" for the conclusion section. We do
    #     not want '[Auto-locked at migration]' surfacing in GxP exports.
    #   - `conclusion_locked_by_name = 'system'` is audit-defensible *only*
    #     in concert with the runbook comment below.
    #   - WHERE clause includes `conclusion_locked_at IS NULL` so this is
    #     idempotent across a downgrade→re-upgrade cycle; if a customer
    #     locked between cycles, their real signature is preserved.
    #   - Run in autocommit_block so the backfill does not extend the
    #     Alembic migration transaction's lock window on large tables.
    #
    # RUNBOOK ENTRY (for FDA-inspection narratives):
    #   "Experiments locked by this migration carry
    #    conclusion_locked_by_name = 'system' and conclusion = NULL.
    #    No human decision was made about these conclusions. Lock was
    #    applied to preserve the previously-displayed COMPLETE lifecycle
    #    state during the F-0043 phases 4-7 deploy. Locked experiments
    #    can be unlocked by an org admin via the standard unlock flow."
    with op.get_context().autocommit_block():
        op.execute(
            """
            UPDATE experiments e
            SET conclusion_locked_at = NOW(),
                conclusion_locked_by_id = NULL,
                conclusion_locked_by_name = 'system'
            WHERE conclusion_locked_at IS NULL
              AND conclusion IS NULL
              AND EXISTS (SELECT 1 FROM runs r WHERE r.experiment_id = e.id)
              AND NOT EXISTS (
                SELECT 1 FROM runs r
                WHERE r.experiment_id = e.id
                  AND r.status IN ('PLANNED', 'ACTIVE', 'EDITED')
              )
            """
        )


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS ck_runs_key_result_value_finite")
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS ck_runs_key_result_paired")
    op.drop_column("runs", "key_result_unit")
    op.drop_column("runs", "key_result_value")
    op.drop_column("runs", "key_result_label")
    op.drop_constraint(
        "fk_experiments_conclusion_locked_by_id",
        "experiments",
        type_="foreignkey",
    )
    op.drop_column("experiments", "conclusion_locked_by_name")
    op.drop_column("experiments", "conclusion_locked_by_id")
    op.drop_column("experiments", "conclusion_locked_at")
    op.drop_column("experiments", "conclusion")

"""add experiment objective fields and indexes

Revision ID: 110e8c13b63c
Revises: aea60923549a
Create Date: 2026-05-21 10:59:17.977019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = '110e8c13b63c'
down_revision: Union[str, Sequence[str], None] = 'aea60923549a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Schema — three new columns on experiments.
    op.add_column("experiments", sa.Column("objective", sa.Text(), nullable=True))
    op.add_column(
        "experiments",
        sa.Column(
            "success_criteria",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "experiments",
        sa.Column(
            "created_by_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 2. Status normalization — collapse legacy ACTIVE/COMPLETED so the column
    #    means only "archived or not" (Phase 3 reads only ARCHIVED from it).
    #    Done before the index step so the indexes are built on the final shape.
    op.execute(
        "UPDATE experiments SET status = 'DRAFT' "
        "WHERE status NOT IN ('DRAFT', 'ARCHIVED')"
    )

    # 3. Indexes — the GET /experiments listing query is unindexed on main.
    #    Built CONCURRENTLY so the runs table (which can carry hot writes)
    #    is not locked while the index is created. CONCURRENTLY cannot run
    #    inside a transaction, so we exit the surrounding tx via
    #    autocommit_block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_experiments_project_updated "
            "ON experiments (project_id, updated_at DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_runs_experiment_created "
            "ON runs (experiment_id, created_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_experiments_created_by "
            "ON experiments (created_by_id)"
        )


def downgrade() -> None:
    # Schema-only — status normalization is not reversed (one-way; see spec §2.2).
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_runs_experiment_created"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_experiments_created_by"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_experiments_project_updated"
        )
    op.drop_column("experiments", "created_by_id")
    op.drop_column("experiments", "success_criteria")
    op.drop_column("experiments", "objective")

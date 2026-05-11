"""add created_by_id to runs

Adds a `created_by_id` FK on `runs` that records who created the run.
Used to allow PLANNED-state edits by the run creator when the parent
project has permissions_enabled=true (otherwise only project/org admins
or explicit EDIT grantees can edit).

Revision ID: f0038a1b2c3d
Revises: 5f925579ba5a
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0038a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "5f925579ba5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("created_by_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_runs_created_by_id_users",
        "runs",
        "users",
        ["created_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_runs_created_by_id_users", "runs", type_="foreignkey"
    )
    op.drop_column("runs", "created_by_id")

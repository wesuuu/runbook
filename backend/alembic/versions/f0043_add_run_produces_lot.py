"""add produces_lot column and lot_number index (F-0086)

Revision ID: f0043
Revises: 292437ab60e0
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f0043"
down_revision: Union[str, Sequence[str], None] = "292437ab60e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "produces_lot",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_runs_produces_lot",
        "runs",
        ["produces_lot"],
    )
    op.create_index(
        "ix_runs_lot_number",
        "runs",
        ["lot_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_runs_lot_number", table_name="runs")
    op.drop_index("ix_runs_produces_lot", table_name="runs")
    op.drop_column("runs", "produces_lot")

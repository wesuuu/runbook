"""add run production metadata (QA-0008)

Revision ID: 92481a566f44
Revises: cf920d9c14ed
Create Date: 2026-05-15 06:45:36.544798

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "92481a566f44"
down_revision: Union[str, Sequence[str], None] = "cf920d9c14ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "runs",
        sa.Column("lot_number", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("batch_number", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "batch_number")
    op.drop_column("runs", "lot_number")

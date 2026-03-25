"""Add QUEUED and READY document statuses

Revision ID: c7f1a2b3d4e5
Revises: b3a7c9e21f04
Create Date: 2026-03-20 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c7f1a2b3d4e5"
down_revision: Union[str, None] = "b3a7c9e21f04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Status column is varchar — no enum type to alter.
    # Update existing ENRICHED rows to READY so they use the new status.
    op.execute(
        "UPDATE documents SET status = 'READY' WHERE status = 'ENRICHED'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE documents SET status = 'ENRICHED' WHERE status = 'READY'"
    )

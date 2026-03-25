"""Add heartbeat_at to background_jobs

Revision ID: b3a7c9e21f04
Revises: 4b2e86d86981
Create Date: 2026-03-20 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3a7c9e21f04"
down_revision: Union[str, None] = "4b2e86d86981"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "background_jobs",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("background_jobs", "heartbeat_at")

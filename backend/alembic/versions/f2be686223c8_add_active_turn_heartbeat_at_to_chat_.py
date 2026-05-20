"""add active_turn_heartbeat_at to chat_sessions

Revision ID: f2be686223c8
Revises: f0087_qau_org_role
Create Date: 2026-05-20 15:19:20.668568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2be686223c8'
down_revision: Union[str, Sequence[str], None] = 'f0087_qau_org_role'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("active_turn_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "active_turn_heartbeat_at")

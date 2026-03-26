"""Add ai_message_history JSONB column to chat_sessions.

Stores serialized pydantic-ai message objects (including tool calls
and results) for cross-turn context persistence.

Revision ID: f0036a1b2c3d
Revises: f0035a1b2c3d
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "f0036a1b2c3d"
down_revision = "f0035a1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("ai_message_history", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "ai_message_history")

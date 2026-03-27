"""add_context_window_to_ai_provider_configs

Revision ID: 1b5484e8a87e
Revises: f0037a1b2c3d
Create Date: 2026-03-27 10:30:53.443296

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1b5484e8a87e'
down_revision: Union[str, Sequence[str], None] = 'f0037a1b2c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'ai_provider_configs',
        sa.Column('context_window', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ai_provider_configs', 'context_window')

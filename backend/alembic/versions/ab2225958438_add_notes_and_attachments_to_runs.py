"""add_notes_and_attachments_to_runs

Revision ID: ab2225958438
Revises: 96d855d179d4
Create Date: 2026-03-28 00:19:00.645426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ab2225958438'
down_revision: Union[str, Sequence[str], None] = '96d855d179d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add notes and attachments JSONB columns to runs table."""
    op.add_column(
        'runs',
        sa.Column(
            'notes',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )
    op.add_column(
        'runs',
        sa.Column(
            'attachments',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove notes and attachments columns from runs table."""
    op.drop_column('runs', 'attachments')
    op.drop_column('runs', 'notes')

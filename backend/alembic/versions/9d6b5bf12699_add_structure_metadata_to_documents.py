"""add_structure_metadata_to_documents

Revision ID: 9d6b5bf12699
Revises: 4d5bd286bd0a
Create Date: 2026-03-20 11:53:46.550122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9d6b5bf12699'
down_revision: Union[str, Sequence[str], None] = '4d5bd286bd0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('structure_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'structure_metadata')

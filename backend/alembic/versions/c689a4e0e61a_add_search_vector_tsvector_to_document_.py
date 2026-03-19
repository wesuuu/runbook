"""add_search_vector_tsvector_to_document_chunks

Revision ID: c689a4e0e61a
Revises: df68f6215a5d
Create Date: 2026-03-18 16:15:42.143705

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c689a4e0e61a'
down_revision: Union[str, Sequence[str], None] = 'df68f6215a5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tsvector generated column and GIN index for full-text search."""
    # Add a stored generated column that auto-computes tsvector from content.
    # 'english' config gives us stemming (e.g., "passaging" matches "passage").
    op.execute("""
        ALTER TABLE document_chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)

    # GIN index for fast full-text lookups
    op.execute("""
        CREATE INDEX ix_chunk_search_vector
        ON document_chunks
        USING gin (search_vector)
    """)


def downgrade() -> None:
    """Remove tsvector column and index."""
    op.execute("DROP INDEX IF EXISTS ix_chunk_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")

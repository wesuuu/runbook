"""add protocol gxp metadata fields (QA-0008)

Revision ID: cf920d9c14ed
Revises: f0041
Create Date: 2026-05-15 06:35:37.575180

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf920d9c14ed"
down_revision: Union[str, Sequence[str], None] = "f0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "protocol_versions",
        sa.Column("doc_number", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "protocol_versions", sa.Column("effective_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "protocol_versions", sa.Column("supersedes_date", sa.Date(), nullable=True)
    )
    op.add_column("protocol_versions", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("protocol_versions", sa.Column("scope", sa.Text(), nullable=True))
    op.add_column(
        "protocol_versions", sa.Column("references", sa.Text(), nullable=True)
    )
    op.add_column(
        "protocol_versions", sa.Column("definitions", sa.Text(), nullable=True)
    )
    op.add_column(
        "protocols", sa.Column("doc_number", sa.String(length=64), nullable=True)
    )
    op.add_column("protocols", sa.Column("effective_date", sa.Date(), nullable=True))
    op.add_column("protocols", sa.Column("supersedes_date", sa.Date(), nullable=True))
    op.add_column("protocols", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("protocols", sa.Column("scope", sa.Text(), nullable=True))
    op.add_column("protocols", sa.Column("references", sa.Text(), nullable=True))
    op.add_column("protocols", sa.Column("definitions", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("protocols", "definitions")
    op.drop_column("protocols", "references")
    op.drop_column("protocols", "scope")
    op.drop_column("protocols", "purpose")
    op.drop_column("protocols", "supersedes_date")
    op.drop_column("protocols", "effective_date")
    op.drop_column("protocols", "doc_number")
    op.drop_column("protocol_versions", "definitions")
    op.drop_column("protocol_versions", "references")
    op.drop_column("protocol_versions", "scope")
    op.drop_column("protocol_versions", "purpose")
    op.drop_column("protocol_versions", "supersedes_date")
    op.drop_column("protocol_versions", "effective_date")
    op.drop_column("protocol_versions", "doc_number")

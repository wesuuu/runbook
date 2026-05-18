"""add extraction heartbeat columns

Revision ID: f0042_add_extraction_heartbeat_columns
Revises: f0041_docling_document_columns
Create Date: 2026-05-13

"""

from alembic import op
import sqlalchemy as sa

revision = "f0042_add_heartbeat_columns"
down_revision = "f0041_docling_document_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("heartbeat_token", sa.String(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "last_heartbeat_at")
    op.drop_column("documents", "heartbeat_token")

"""Enforce 150-char max on document titles.

Truncate existing titles that exceed the limit, then alter the column
to VARCHAR(150) so the constraint is enforced at the DB level.

Revision ID: f0035
Revises: f0034_add_subscription_tier_and_selected_org
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f0035a1b2c3d"
down_revision = "f0022b1c2d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Truncate any existing titles longer than 150 characters
    op.execute("UPDATE documents SET title = LEFT(title, 150) WHERE LENGTH(title) > 150")
    # Alter column to enforce VARCHAR(150)
    op.alter_column(
        "documents",
        "title",
        existing_type=sa.String(),
        type_=sa.String(150),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Revert to unbounded String
    op.alter_column(
        "documents",
        "title",
        existing_type=sa.String(150),
        type_=sa.String(),
        existing_nullable=False,
    )

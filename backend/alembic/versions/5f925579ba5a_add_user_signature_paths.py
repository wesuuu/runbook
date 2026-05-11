"""add user signature paths

Revision ID: 5f925579ba5a
Revises: 8f69beb214a4
Create Date: 2026-04-30 09:04:09.472872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f925579ba5a'
down_revision: Union[str, Sequence[str], None] = '8f69beb214a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("signature_initials_path", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("signature_full_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "signature_full_path")
    op.drop_column("users", "signature_initials_path")

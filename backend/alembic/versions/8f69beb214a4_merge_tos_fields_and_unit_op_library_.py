"""merge tos fields and unit op library heads

Revision ID: 8f69beb214a4
Revises: e3bd9a91ed09, f0020a1b2c3d
Create Date: 2026-04-30 08:57:12.159374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f69beb214a4'
down_revision: Union[str, Sequence[str], None] = ('e3bd9a91ed09', 'f0020a1b2c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

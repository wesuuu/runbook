"""merge td0091c and experiment-objective heads

Revision ID: 0b79aaec97ca
Revises: 110e8c13b63c, td0091c_c_backfill
Create Date: 2026-05-22 23:06:51.663107

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b79aaec97ca'
down_revision: Union[str, Sequence[str], None] = ('110e8c13b63c', 'td0091c_c_backfill')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

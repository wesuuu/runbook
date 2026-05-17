"""merge qa-0008 + td-0085 heads

Revision ID: 292437ab60e0
Revises: 92481a566f44, f0042_add_heartbeat_columns
Create Date: 2026-05-17 15:40:03.750975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '292437ab60e0'
down_revision: Union[str, Sequence[str], None] = ('92481a566f44', 'f0042_add_heartbeat_columns')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

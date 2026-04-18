"""merge branches

Revision ID: 2a425e3691af
Revises: 22cea73d75b4, 6ec61c5f91b8
Create Date: 2026-04-17 23:52:19.374176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a425e3691af'
down_revision: Union[str, Sequence[str], None] = ('22cea73d75b4', '6ec61c5f91b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""merge f0080 signoff queue and f0092 dashboard heads

Revision ID: 3cbfb1725385
Revises: 5edbee91ef25, a0bae907660e
Create Date: 2026-05-21 14:48:56.013962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cbfb1725385'
down_revision: Union[str, Sequence[str], None] = ('5edbee91ef25', 'a0bae907660e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

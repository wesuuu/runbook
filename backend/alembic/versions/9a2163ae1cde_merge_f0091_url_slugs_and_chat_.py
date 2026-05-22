"""merge f0091 url-slugs and chat heartbeat heads

Revision ID: 9a2163ae1cde
Revises: f0091_url_slugs, f2be686223c8
Create Date: 2026-05-21 16:16:59.284198

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a2163ae1cde'
down_revision: Union[str, Sequence[str], None] = ('f0091_url_slugs', 'f2be686223c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

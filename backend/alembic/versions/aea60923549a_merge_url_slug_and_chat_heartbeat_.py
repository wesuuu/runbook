"""merge url-slug and chat-heartbeat migration heads

Revision ID: aea60923549a
Revises: f0091_url_slugs, f2be686223c8
Create Date: 2026-05-21 10:40:56.264486

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aea60923549a'
down_revision: Union[str, Sequence[str], None] = ('f0091_url_slugs', 'f2be686223c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

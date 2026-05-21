"""merge f0080 signoff with url-slug and chat-heartbeat heads

Revision ID: 5edbee91ef25
Revises: f0080_run_signoff_requests, f0091_url_slugs, f2be686223c8
Create Date: 2026-05-21 13:31:11.754165

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5edbee91ef25'
down_revision: Union[str, Sequence[str], None] = ('f0080_run_signoff_requests', 'f0091_url_slugs', 'f2be686223c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

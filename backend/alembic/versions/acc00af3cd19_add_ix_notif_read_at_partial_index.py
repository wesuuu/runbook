"""add ix_notif_read_at partial index

Revision ID: acc00af3cd19
Revises: 9a2163ae1cde
Create Date: 2026-05-21 20:41:23.391682

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acc00af3cd19'
down_revision: Union[str, Sequence[str], None] = '9a2163ae1cde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block;
    # autocommit_block suspends Alembic's per-migration transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notif_read_at "
            "ON notifications (read_at) WHERE read_at IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notif_read_at")

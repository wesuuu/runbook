"""F-0043 — partial index on conclusion_locked_by_id

Followup to ``92ca639b721b``. The unlock endpoint and audit-trail queries
need to find "experiments locked by user X" without scanning the whole
table. Locked rows are a small fraction of the table, so a partial index
(WHERE conclusion_locked_by_id IS NOT NULL) stays tiny and selective.

CREATE INDEX CONCURRENTLY runs outside the migration transaction so it
doesn't hold an AccessExclusiveLock on a hot table during deploys.
"""

from typing import Sequence, Union

from alembic import op


revision: str = 'f0043_lock_partial_idx'
down_revision: Union[str, Sequence[str], None] = '92ca639b721b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_experiments_conclusion_locked_by_id "
            "ON experiments (conclusion_locked_by_id) "
            "WHERE conclusion_locked_by_id IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_experiments_conclusion_locked_by_id"
        )

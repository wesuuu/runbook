"""add notification payload

Revision ID: 3a6f1292915b
Revises: 0b79aaec97ca
Create Date: 2026-05-22 23:07:06.469095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3a6f1292915b'
down_revision: Union[str, Sequence[str], None] = '0b79aaec97ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # NOT VALID skips the full-table scan under ShareRowExclusiveLock that a
    # plain ADD CONSTRAINT would take. Newly-written rows are still gated by
    # the check; VALIDATE then scans existing rows without blocking writes.
    op.execute(
        "ALTER TABLE notifications ADD CONSTRAINT "
        "ck_notifications_payload_size "
        "CHECK (octet_length(payload::text) <= 512) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TABLE notifications VALIDATE CONSTRAINT "
            "ck_notifications_payload_size"
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notifications_payload_size",
        "notifications",
        type_="check",
    )
    op.drop_column("notifications", "payload")

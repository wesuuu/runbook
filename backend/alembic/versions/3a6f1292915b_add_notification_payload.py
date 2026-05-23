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
    op.create_check_constraint(
        "ck_notifications_payload_size",
        "notifications",
        "octet_length(payload::text) <= 512",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notifications_payload_size",
        "notifications",
        type_="check",
    )
    op.drop_column("notifications", "payload")

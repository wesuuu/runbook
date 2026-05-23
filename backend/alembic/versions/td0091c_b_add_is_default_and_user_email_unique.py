"""TD-0091c: add is_default + unique partial index + run_role_assign run_id index.

Revision ID: td0091c_b_ddl
Revises: td0091c_a_merge
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "td0091c_b_ddl"
down_revision: Union[str, Sequence[str], None] = "td0091c_a_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_channels",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_notif_channel_user_email_unique",
        "notification_channels",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "channel_type = 'EMAIL' AND is_default = TRUE "
            "AND user_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_run_role_assign_run_id",
        "run_role_assignments",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_run_role_assign_run_id",
        table_name="run_role_assignments",
    )
    op.drop_index(
        "ix_notif_channel_user_email_unique",
        table_name="notification_channels",
    )
    op.drop_column("notification_channels", "is_default")

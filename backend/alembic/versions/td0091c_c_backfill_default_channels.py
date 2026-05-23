"""TD-0091c: backfill default EMAIL channels + subscriptions for existing users.

Revision ID: td0091c_c_backfill
Revises: td0091c_b_ddl
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "td0091c_c_backfill"
down_revision: Union[str, Sequence[str], None] = "td0091c_b_ddl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill in two passes, each inside autocommit_block so each row
    commits independently and we don't hold a long lock on either table."""
    bind = op.get_bind()

    # Pass 1: one EMAIL channel per user who lacks one. is_default=true
    # marks the row as owned by the auto-provisioning path.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
            INSERT INTO notification_channels
              (id, user_id, name, channel_type, config, enabled, is_default,
               created_at, updated_at)
            SELECT
              gen_random_uuid(), u.id, 'Email', 'EMAIL',
              jsonb_build_object('to', u.email), true, true, now(), now()
            FROM users u
            WHERE NOT EXISTS (
              SELECT 1 FROM notification_channels c
              WHERE c.user_id = u.id AND c.channel_type = 'EMAIL'
            )
            ON CONFLICT DO NOTHING
        """))

        pass1_count = bind.execute(sa.text("""
            SELECT COUNT(*) FROM notification_channels
            WHERE is_default = TRUE AND channel_type = 'EMAIL'
        """)).scalar()
        print(
            f"[td0091c_c] Pass 1 complete: {pass1_count} default EMAIL channels exist",
            flush=True,
        )

    # Pass 2: seed default-email subscriptions on every per-user EMAIL channel
    # that's missing them. Re-runnable.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
            INSERT INTO notification_subscriptions
              (id, channel_id, event_type, enabled, created_at, updated_at)
            SELECT gen_random_uuid(), c.id, e.event_type, true, now(), now()
            FROM notification_channels c
            CROSS JOIN (VALUES
              ('RUN_STARTED'),
              ('ROLE_ASSIGNED'),
              ('ROLE_REASSIGNED'),
              ('ROLE_UNASSIGNED'),
              ('INVITE_SENT'),
              ('PROTOCOL_APPROVAL_REQUESTED'),
              ('PROTOCOL_APPROVED'),
              ('RUN_SIGNOFF_REQUESTED')
            ) AS e(event_type)
            WHERE c.channel_type = 'EMAIL'
              AND c.user_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM notification_subscriptions s
                WHERE s.channel_id = c.id AND s.event_type = e.event_type
              )
        """))

        pass2_count = bind.execute(sa.text("""
            SELECT COUNT(*) FROM notification_subscriptions s
            JOIN notification_channels c ON c.id = s.channel_id
            WHERE c.is_default = TRUE AND c.channel_type = 'EMAIL'
        """)).scalar()
        print(
            f"[td0091c_c] Pass 2 complete: {pass2_count} subscriptions on default channels",
            flush=True,
        )


def downgrade() -> None:
    """Delete only the auto-provisioned channels (is_default=true).
    Cascade clears subscriptions. User-created channels are untouched."""
    bind = op.get_bind()
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
            DELETE FROM notification_channels
            WHERE is_default = TRUE
        """))

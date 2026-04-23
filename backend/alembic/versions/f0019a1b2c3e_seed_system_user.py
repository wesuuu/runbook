"""Seed the system actor user referenced by audit entries from webhook
and background code (where there is no authenticated user).

Revision ID: f0019a1b2c3e
Revises: f0019a1b2c3d
Create Date: 2026-04-23
"""

from alembic import op

revision = "f0019a1b2c3e"
down_revision = "f0019a1b2c3d"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO users (id, email, full_name, hashed_password,
                           email_verified, is_active, created_at, updated_at)
        VALUES ('00000000-0000-0000-0000-000000000000',
                'system@batchrite.internal', 'System',
                '!system-locked!', true, false, now(), now())
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade():
    op.execute(
        "DELETE FROM users WHERE id = '00000000-0000-0000-0000-000000000000'"
    )

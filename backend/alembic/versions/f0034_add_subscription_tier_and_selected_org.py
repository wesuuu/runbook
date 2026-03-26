"""add subscription_tier to organizations and selected_org_id to users

Revision ID: f0034a1b2c3d
Revises: c7f1a2b3d4e5
Create Date: 2026-03-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f0034a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "c7f1a2b3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add subscription_tier to organizations
    op.add_column(
        "organizations",
        sa.Column(
            "subscription_tier",
            sa.String(),
            nullable=False,
            server_default="essentials",
        ),
    )

    # 2. Add selected_org_id to users (nullable)
    op.add_column(
        "users",
        sa.Column(
            "selected_org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
    )

    # 3. Backfill selected_org_id for users who have org memberships
    #    Pick their earliest org membership
    op.execute("""
        UPDATE users u
        SET selected_org_id = sub.organization_id
        FROM (
            SELECT DISTINCT ON (user_id) user_id, organization_id
            FROM organization_members
            ORDER BY user_id, created_at ASC
        ) sub
        WHERE u.id = sub.user_id
          AND u.selected_org_id IS NULL
    """)

    # 4. Backfill orphan users (no org membership) — assign to most popular org
    #    Also create organization_members rows for them
    op.execute("""
        WITH most_popular_org AS (
            SELECT organization_id, COUNT(*) as cnt
            FROM organization_members
            GROUP BY organization_id
            ORDER BY cnt DESC
            LIMIT 1
        )
        UPDATE users u
        SET selected_org_id = mpo.organization_id
        FROM most_popular_org mpo
        WHERE u.selected_org_id IS NULL
    """)

    op.execute("""
        INSERT INTO organization_members (id, user_id, organization_id, role, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            u.id,
            u.selected_org_id,
            'MEMBER',
            NOW(),
            NOW()
        FROM users u
        WHERE u.selected_org_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM organization_members om
              WHERE om.user_id = u.id AND om.organization_id = u.selected_org_id
          )
    """)


def downgrade() -> None:
    op.drop_column("users", "selected_org_id")
    op.drop_column("organizations", "subscription_tier")

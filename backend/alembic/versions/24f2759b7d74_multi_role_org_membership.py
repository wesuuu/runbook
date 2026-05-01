"""multi_role_org_membership

Revision ID: 24f2759b7d74
Revises: f0038a1b2c3d
Create Date: 2026-05-01 13:46:24.424094

Replace `organization_members.role` (single string) with `roles` (varchar[]):
backfill from the legacy column (deduped, MEMBER always present), enforce
allowed values via CHECK constraint, then drop the legacy column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '24f2759b7d74'
down_revision: Union[str, Sequence[str], None] = 'f0038a1b2c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add `roles` column with default
    op.add_column(
        "organization_members",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['MEMBER']::varchar[]"),
        ),
    )
    # 2. Backfill from legacy `role` column (deduped, MEMBER always present)
    op.execute(
        """
        UPDATE organization_members
        SET roles = ARRAY(
            SELECT DISTINCT unnest(ARRAY[role, 'MEMBER'])
        )
        """
    )
    # 3. Enforce allowed values
    op.execute(
        """
        ALTER TABLE organization_members
        ADD CONSTRAINT ck_org_member_roles
        CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])
        """
    )
    # 4. Drop legacy column
    op.drop_column("organization_members", "role")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "organization_members",
        sa.Column("role", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE organization_members
        SET role = CASE
            WHEN 'ADMIN' = ANY(roles) THEN 'ADMIN'
            WHEN 'BILLING' = ANY(roles) THEN 'BILLING'
            ELSE 'MEMBER'
        END
        """
    )
    op.alter_column("organization_members", "role", nullable=False)
    op.execute(
        "ALTER TABLE organization_members DROP CONSTRAINT ck_org_member_roles"
    )
    op.drop_column("organization_members", "roles")

"""org and team role enums

Revision ID: 83fbf6595e21
Revises: 6cec74d0f700
Create Date: 2026-03-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83fbf6595e21'
down_revision: Union[str, None] = '6cec74d0f700'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert organization_members.is_admin (boolean) to role (string)
    op.add_column(
        'organization_members',
        sa.Column('role', sa.String(), nullable=True),
    )
    # Migrate data: is_admin=true -> ADMIN, else -> MEMBER
    op.execute(
        "UPDATE organization_members SET role = CASE "
        "WHEN is_admin = true THEN 'ADMIN' ELSE 'MEMBER' END"
    )
    op.alter_column('organization_members', 'role', nullable=False)
    op.drop_column('organization_members', 'is_admin')

    # Convert team_members.role from OWNER/MEMBER/VIEWER to LEAD/MEMBER
    op.execute(
        "UPDATE team_members SET role = 'LEAD' WHERE role = 'OWNER'"
    )
    op.execute(
        "UPDATE team_members SET role = 'MEMBER' WHERE role = 'VIEWER'"
    )


def downgrade() -> None:
    # Convert role back to is_admin
    op.add_column(
        'organization_members',
        sa.Column('is_admin', sa.Boolean(), nullable=True),
    )
    op.execute(
        "UPDATE organization_members SET is_admin = (role = 'ADMIN')"
    )
    op.alter_column('organization_members', 'is_admin', nullable=False)
    op.drop_column('organization_members', 'role')

    # Revert team roles
    op.execute(
        "UPDATE team_members SET role = 'OWNER' WHERE role = 'LEAD'"
    )

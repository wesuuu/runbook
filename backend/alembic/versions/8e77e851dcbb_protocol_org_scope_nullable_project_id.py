"""protocol_org_scope_nullable_project_id

Revision ID: 8e77e851dcbb
Revises: ab12f8fb0bc4
Create Date: 2026-04-03 12:05:19.724438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8e77e851dcbb'
down_revision: Union[str, Sequence[str], None] = 'ab12f8fb0bc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make Protocol.project_id nullable and add organization_id for org-scoped protocols."""
    op.add_column('protocols', sa.Column('organization_id', sa.UUID(), nullable=True))
    op.alter_column('protocols', 'project_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.create_foreign_key(
        'fk_protocols_organization_id',
        'protocols', 'organizations',
        ['organization_id'], ['id'],
    )
    op.create_check_constraint(
        'ck_protocol_scope',
        'protocols',
        "(project_id IS NOT NULL AND organization_id IS NULL) OR "
        "(project_id IS NULL AND organization_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Revert: drop organization_id, make project_id required again."""
    op.drop_constraint('ck_protocol_scope', 'protocols', type_='check')
    op.drop_constraint('fk_protocols_organization_id', 'protocols', type_='foreignkey')
    op.alter_column('protocols', 'project_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('protocols', 'organization_id')

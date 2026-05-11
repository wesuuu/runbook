"""fix object_permission unique constraint to include permission_level

Revision ID: f0040
Revises: f0039_protocol_approval
Create Date: 2026-05-10

The original uq_object_permission constraint covered
(principal_type, principal_id, object_type, object_id) without permission_level.
This prevented a user from having both an EDIT permission and an APPROVE permission
on the same project - a valid use case for project protocol approval flows.

Fix: drop the old constraint and recreate it with permission_level included.
"""
from alembic import op

# revision identifiers
revision = 'f0040'
down_revision = 'f0039_protocol_approval'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uq_object_permission', 'object_permissions', type_='unique')
    op.create_unique_constraint(
        'uq_object_permission',
        'object_permissions',
        ['principal_type', 'principal_id', 'object_type', 'object_id', 'permission_level'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_object_permission', 'object_permissions', type_='unique')
    op.create_unique_constraint(
        'uq_object_permission',
        'object_permissions',
        ['principal_type', 'principal_id', 'object_type', 'object_id'],
    )

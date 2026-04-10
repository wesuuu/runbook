"""add invitations table and archived column to org members

Revision ID: 22cea73d75b4
Revises: 39ec554a844a
Create Date: 2026-04-09 16:23:01.086711

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22cea73d75b4'
down_revision: Union[str, Sequence[str], None] = '39ec554a844a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Invitations table
    op.create_table('invitations',
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('invited_email', sa.String(), nullable=False),
        sa.Column('invited_user_id', sa.UUID(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='PENDING', nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id']),
        sa.ForeignKeyConstraint(['invited_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invitation_token', 'invitations', ['token'], unique=True)
    op.create_index(
        'ix_pending_invitation', 'invitations',
        ['organization_id', 'invited_email'],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # Archived column on organization_members
    op.add_column('organization_members',
        sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organization_members', 'archived')
    op.drop_index('ix_pending_invitation', table_name='invitations')
    op.drop_index('ix_invitation_token', table_name='invitations')
    op.drop_table('invitations')

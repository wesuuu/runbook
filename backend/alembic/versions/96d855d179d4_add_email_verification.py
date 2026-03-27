"""add email verification

Revision ID: 96d855d179d4
Revises: 1b5484e8a87e
Create Date: 2026-03-27 11:19:59.697298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96d855d179d4'
down_revision: Union[str, Sequence[str], None] = '1b5484e8a87e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create verification_tokens table
    op.create_table(
        'verification_tokens',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_verification_tokens_token'),
        'verification_tokens', ['token'], unique=True,
    )

    # 2. Add email_verified to users — existing users grandfathered as True
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    # 3. Change default to false for new users
    op.alter_column('users', 'email_verified', server_default=sa.text('false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'email_verified')
    op.drop_index(op.f('ix_verification_tokens_token'), table_name='verification_tokens')
    op.drop_table('verification_tokens')

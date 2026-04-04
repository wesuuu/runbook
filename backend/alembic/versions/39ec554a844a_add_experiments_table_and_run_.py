"""add_experiments_table_and_run_experiment_id

Revision ID: 39ec554a844a
Revises: 8e77e851dcbb
Create Date: 2026-04-04 12:35:44.957259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '39ec554a844a'
down_revision: Union[str, Sequence[str], None] = '8e77e851dcbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add experiments table and runs.experiment_id FK."""
    op.create_table(
        'experiments',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False),
        sa.Column('status', sa.String(), server_default='DRAFT',
                  nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('notes', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='[]', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_experiments_project_id', 'experiments', ['project_id'],
    )

    op.add_column(
        'runs', sa.Column('experiment_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_runs_experiment_id', 'runs', 'experiments',
        ['experiment_id'], ['id'],
    )
    op.create_index(
        'ix_runs_experiment_id', 'runs', ['experiment_id'],
    )


def downgrade() -> None:
    """Remove experiments table and runs.experiment_id FK."""
    op.drop_index('ix_runs_experiment_id', table_name='runs')
    op.drop_constraint('fk_runs_experiment_id', 'runs', type_='foreignkey')
    op.drop_column('runs', 'experiment_id')
    op.drop_index('ix_experiments_project_id', table_name='experiments')
    op.drop_table('experiments')

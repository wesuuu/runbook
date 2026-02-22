"""rename experiments to runs

Revision ID: a1b2c3d4e5f6
Revises: 4f2d80e9ab5e
Create Date: 2026-02-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4f2d80e9ab5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename experiments -> runs tables and columns."""
    # Rename main table
    op.rename_table('experiments', 'runs')

    # Rename role assignments table
    op.rename_table('experiment_role_assignments', 'run_role_assignments')

    # Rename column in run_role_assignments
    op.alter_column(
        'run_role_assignments',
        'experiment_id',
        new_column_name='run_id',
    )

    # Update object_permissions enum values
    op.execute(
        "UPDATE object_permissions SET object_type = 'RUN' "
        "WHERE object_type = 'EXPERIMENT'"
    )


def downgrade() -> None:
    """Revert runs -> experiments."""
    # Revert object_permissions enum values
    op.execute(
        "UPDATE object_permissions SET object_type = 'EXPERIMENT' "
        "WHERE object_type = 'RUN'"
    )

    # Revert column rename
    op.alter_column(
        'run_role_assignments',
        'run_id',
        new_column_name='experiment_id',
    )

    # Revert table renames
    op.rename_table('run_role_assignments', 'experiment_role_assignments')
    op.rename_table('runs', 'experiments')

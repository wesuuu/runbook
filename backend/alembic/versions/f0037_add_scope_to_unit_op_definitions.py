"""Add organization_id and project_id scope columns to unit_op_definitions.

Enables multi-scope unit operations: global (NULL/NULL), org-scoped, and
project-scoped. Existing rows remain global. Adds CHECK constraint to
prevent project_id without organization_id.

Revision ID: f0037a1b2c3d
Revises: f0036a1b2c3d
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f0037a1b2c3d"
down_revision = "f0036a1b2c3d"
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable scope columns — existing rows stay NULL (global)
    op.add_column(
        "unit_op_definitions",
        sa.Column("organization_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "unit_op_definitions",
        sa.Column("project_id", sa.UUID(), nullable=True),
    )

    # Foreign keys
    op.create_foreign_key(
        "fk_unit_op_organization",
        "unit_op_definitions",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_unit_op_project",
        "unit_op_definitions",
        "projects",
        ["project_id"],
        ["id"],
    )

    # CHECK: project_id requires organization_id
    op.create_check_constraint(
        "ck_unit_op_scope_valid",
        "unit_op_definitions",
        "project_id IS NULL OR organization_id IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("ck_unit_op_scope_valid", "unit_op_definitions")
    op.drop_constraint("fk_unit_op_project", "unit_op_definitions", type_="foreignkey")
    op.drop_constraint("fk_unit_op_organization", "unit_op_definitions", type_="foreignkey")
    op.drop_column("unit_op_definitions", "project_id")
    op.drop_column("unit_op_definitions", "organization_id")

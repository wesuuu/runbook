"""unit op library abstraction

Revision ID: e3bd9a91ed09
Revises: f0019a1b2c3e
Create Date: 2026-04-27 12:09:37.389559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3bd9a91ed09'
down_revision: Union[str, Sequence[str], None] = 'f0019a1b2c3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unit_op_library_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("library_slug", sa.String(), nullable=False),
        sa.Column(
            "subscribed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "library_slug", name="uq_unit_op_lib_sub",
        ),
    )

    op.add_column(
        "unit_op_definitions",
        sa.Column("source_library_slug", sa.String(), nullable=True),
    )
    op.add_column(
        "unit_op_definitions",
        sa.Column("source_op_slug", sa.String(), nullable=True),
    )

    op.create_check_constraint(
        "ck_unit_op_source_both_or_neither",
        "unit_op_definitions",
        "(source_library_slug IS NULL AND source_op_slug IS NULL) OR "
        "(source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)",
    )

    # Drop existing global rows. Protocol graphs that reference them
    # become orphan-id references — acceptable per F-0075 spec.
    op.execute(
        "DELETE FROM unit_op_definitions "
        "WHERE organization_id IS NULL AND project_id IS NULL"
    )

    # Backfill subscriptions: every existing org gets the 'core' library.
    op.execute(
        "INSERT INTO unit_op_library_subscriptions "
        "(id, organization_id, library_slug, subscribed_at, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, 'core', now(), now(), now() "
        "FROM organizations"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_unit_op_source_both_or_neither",
        "unit_op_definitions",
        type_="check",
    )
    op.drop_column("unit_op_definitions", "source_op_slug")
    op.drop_column("unit_op_definitions", "source_library_slug")
    op.drop_table("unit_op_library_subscriptions")

"""add org_id to ai_provider_configs for per-org scoping

Revision ID: f0022a1b2c3d
Revises: f0034a1b2c3d
Create Date: 2026-03-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f0022a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "f0034a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Delete existing global rows (they have no org_id and can't be
    #    migrated — platform config now lives in env vars, not DB)
    op.execute("DELETE FROM ai_provider_configs")

    # 2. Drop old unique constraint
    op.drop_constraint("uq_ai_capability", "ai_provider_configs", type_="unique")

    # 3. Add org_id column (non-nullable since we cleared all rows)
    op.add_column(
        "ai_provider_configs",
        sa.Column(
            "org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
    )

    # 4. Add new unique constraint
    op.create_unique_constraint(
        "uq_ai_org_capability",
        "ai_provider_configs",
        ["org_id", "capability"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_ai_org_capability", "ai_provider_configs", type_="unique")
    op.drop_column("ai_provider_configs", "org_id")
    op.create_unique_constraint("uq_ai_capability", "ai_provider_configs", ["capability"])

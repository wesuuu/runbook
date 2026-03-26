"""replace api_key and base_url with credentials JSONB on ai_provider_configs

Revision ID: f0022b1c2d3e
Revises: f0022a1b2c3d
Create Date: 2026-03-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0022b1c2d3e"
down_revision: Union[str, Sequence[str], None] = "f0022a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add credentials JSONB
    op.add_column(
        "ai_provider_configs",
        sa.Column("credentials", sa.JSON(), nullable=True),
    )

    # 2. Migrate existing data (api_key + base_url → credentials)
    op.execute("""
        UPDATE ai_provider_configs
        SET credentials = jsonb_strip_nulls(jsonb_build_object(
            'api_key', api_key,
            'base_url', base_url
        ))
        WHERE api_key IS NOT NULL OR base_url IS NOT NULL
    """)

    # 3. Drop old columns
    op.drop_column("ai_provider_configs", "api_key")
    op.drop_column("ai_provider_configs", "base_url")


def downgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("api_key", sa.String(), nullable=True),
    )
    op.add_column(
        "ai_provider_configs",
        sa.Column("base_url", sa.String(), nullable=True),
    )

    op.execute("""
        UPDATE ai_provider_configs
        SET api_key = credentials->>'api_key',
            base_url = credentials->>'base_url'
        WHERE credentials IS NOT NULL
    """)

    op.drop_column("ai_provider_configs", "credentials")

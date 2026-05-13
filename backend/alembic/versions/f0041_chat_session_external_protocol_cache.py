"""chat_session external_protocol_cache jsonb column

Revision ID: f0041
Revises: f0040
Create Date: 2026-05-13

Adds a JSONB column on chat_sessions to durably store payloads fetched by
the protocol_knowledgebase subagent. Previously the cache lived only on
ChatDeps (per-request) and was rehydrated by scraping
EXTERNAL_PROTOCOL_SOURCE fence blocks out of ai_message_history. That
approach is brittle: pydantic-ai compaction elides large tool returns,
and the LLM sometimes drops the fence label — both cases produce empty
approval cards when the user later asks to convert a previously fetched
protocol.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "f0041"
down_revision = "f0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "external_protocol_cache",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "external_protocol_cache")

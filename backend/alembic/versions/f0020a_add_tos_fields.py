"""add tos_accepted_at, tos_version, legal_terms_overridden

Adds three columns supporting the ToS / Privacy acceptance flow:

- users.tos_accepted_at (TIMESTAMP WITH TIME ZONE, nullable) — captures when
  a user accepted the current legal terms.
- users.tos_version (VARCHAR, nullable) — the version string of the terms
  the user accepted, e.g. ``v2026-04-27``.
- organizations.legal_terms_overridden (BOOLEAN, NOT NULL DEFAULT false) —
  set when an org has negotiated custom legal terms (e.g. enterprise
  contract) and should bypass the standard click-through flow.

Revision ID: f0020a1b2c3d
Revises: f0019a1b2c3e
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0020a1b2c3d"
down_revision = "f0019a1b2c3e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "tos_accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("tos_version", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "legal_terms_overridden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("organizations", "legal_terms_overridden")
    op.drop_column("users", "tos_version")
    op.drop_column("users", "tos_accepted_at")

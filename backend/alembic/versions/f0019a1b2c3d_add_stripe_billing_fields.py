"""Add Stripe billing fields to organizations and StripeEvent table.

Adds nullable stripe_customer_id, stripe_subscription_id, subscription_status,
current_period_end, trial_end, cancel_at_period_end, and has_payment_method
columns to organizations. Creates stripe_events table for webhook idempotency.

Revision ID: f0019a1b2c3d
Revises: 248af12c65f7
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "f0019a1b2c3d"
down_revision = "248af12c65f7"
branch_labels = None
depends_on = None


def upgrade():
    # organizations: nullable Stripe state columns
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("subscription_status", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "has_payment_method",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_organizations_stripe_customer_id",
        "organizations",
        ["stripe_customer_id"],
    )

    # stripe_events: idempotency record for processed webhook events
    op.create_table(
        "stripe_events",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("stripe_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_stripe_events_stripe_event_id",
        "stripe_events",
        ["stripe_event_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_stripe_events_stripe_event_id", table_name="stripe_events"
    )
    op.drop_table("stripe_events")

    op.drop_index(
        "ix_organizations_stripe_customer_id", table_name="organizations"
    )
    op.drop_column("organizations", "has_payment_method")
    op.drop_column("organizations", "cancel_at_period_end")
    op.drop_column("organizations", "trial_end")
    op.drop_column("organizations", "current_period_end")
    op.drop_column("organizations", "subscription_status")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")

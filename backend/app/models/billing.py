from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class StripeEvent(Base, UUIDMixin, TimestampMixin):
    """Idempotency record for processed Stripe webhook events.

    Whenever the webhook handler processes a Stripe event, it upserts a row
    keyed by Stripe's event ID. Duplicate deliveries (Stripe retries on
    non-2xx for up to 3 days) are detected here and skipped.
    """

    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)

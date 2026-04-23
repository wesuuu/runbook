"""Per-tier seat caps.

Policy:
  - Essentials: `settings.seat_limit_essentials` (default 5).
  - Pro: `settings.seat_limit_pro` (default 25).
  - Enterprise: unlimited (None).

Enforcement:
  - `check_seat_capacity` raises HTTPException(403) if the org has already hit its cap.
    Callers invoke this immediately before inserting a new non-archived OrganizationMember.
  - Downgrades (via Stripe Portal) are NOT blocked here — they flow through the webhook
    handler unchanged. The resulting overage is surfaced via `seat_limit_exceeded` in
    `GET /billing/subscription`.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iam import Organization, OrganizationMember, SubscriptionTier


def get_seat_limit(tier: SubscriptionTier | str | None) -> int | None:
    """Return the seat cap for a tier, or None for unlimited / unknown tiers."""
    if tier == SubscriptionTier.ESSENTIALS or tier == "essentials":
        return settings.seat_limit_essentials
    if tier == SubscriptionTier.PRO or tier == "pro":
        return settings.seat_limit_pro
    if tier == SubscriptionTier.ENTERPRISE or tier == "enterprise":
        return None
    return None


async def get_seat_count(db: AsyncSession, org_id: UUID) -> int:
    """Count non-archived memberships for an org."""
    result = await db.execute(
        select(func.count()).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,  # noqa: E712
        )
    )
    return int(result.scalar() or 0)


async def check_seat_capacity(db: AsyncSession, org: Organization) -> None:
    """Raise HTTPException(403, seat_limit_reached) if adding a member would exceed the cap.

    Call BEFORE inserting a new OrganizationMember row. Callers that reactivate
    an existing archived member should skip this check — the count doesn't change.
    """
    limit = get_seat_limit(org.subscription_tier)
    if limit is None:
        return
    current = await get_seat_count(db, org.id)
    if current >= limit:
        tier_str = (
            org.subscription_tier.value
            if hasattr(org.subscription_tier, "value")
            else str(org.subscription_tier)
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "seat_limit_reached",
                "message": (
                    f"Your {tier_str.capitalize()} plan allows up to {limit} "
                    "members. Upgrade to Pro to add more."
                ),
                "tier": tier_str,
                "limit": limit,
                "current": current,
            },
        )

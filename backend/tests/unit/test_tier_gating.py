"""Unit tests for subscription tier infrastructure."""

import uuid

import pytest

from app.models.iam import TIER_RANK, SubscriptionTier


class TestSubscriptionTierEnum:
    def test_enum_values(self):
        assert SubscriptionTier.ESSENTIALS.value == "essentials"
        assert SubscriptionTier.PRO.value == "pro"
        assert SubscriptionTier.ENTERPRISE.value == "enterprise"

    def test_enum_from_string(self):
        assert SubscriptionTier("essentials") == SubscriptionTier.ESSENTIALS
        assert SubscriptionTier("pro") == SubscriptionTier.PRO

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError):
            SubscriptionTier("platinum")


class TestTierRank:
    def test_essentials_is_lowest(self):
        assert TIER_RANK[SubscriptionTier.ESSENTIALS] == 0

    def test_enterprise_is_highest(self):
        assert TIER_RANK[SubscriptionTier.ENTERPRISE] == 2

    def test_ordering(self):
        assert TIER_RANK[SubscriptionTier.ESSENTIALS] < TIER_RANK[SubscriptionTier.PRO]
        assert TIER_RANK[SubscriptionTier.PRO] < TIER_RANK[SubscriptionTier.ENTERPRISE]

    def test_all_tiers_have_ranks(self):
        for tier in SubscriptionTier:
            assert tier in TIER_RANK


class TestTokenPayloadWithTier:
    def test_token_preserves_tier(self):
        from app.core.security import create_access_token, decode_access_token

        uid = uuid.uuid4()
        org_id = uuid.uuid4()

        for tier in SubscriptionTier:
            token = create_access_token(
                uid, org_id=org_id, subscription_tier=tier.value
            )
            decoded = decode_access_token(token)
            assert decoded is not None
            assert decoded.subscription_tier == tier.value

    def test_token_defaults_to_essentials(self):
        from app.core.security import create_access_token, decode_access_token

        uid = uuid.uuid4()
        token = create_access_token(uid)
        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded.subscription_tier == "essentials"

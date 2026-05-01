"""Integration tests for subscription tier infrastructure."""

import uuid

import pytest
import pytest_asyncio

from app.core.security import create_access_token, hash_password
from app.models.iam import (Organization, OrganizationMember, SubscriptionTier,
                            User)


class TestLoginIncludesOrgContext:
    """Login endpoint should include org_id and tier in the JWT."""

    @pytest.mark.asyncio
    async def test_login_returns_token_with_org_tier(self, client, db_session):
        org = Organization(name="Tier Test Org", subscription_tier="pro")
        db_session.add(org)
        await db_session.flush()

        user = User(
            email="tiertest@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Tier Tester",
            selected_org_id=org.id,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=org.id,
                roles=["MEMBER", "ADMIN"],
            )
        )
        await db_session.flush()

        resp = await client.post(
            "/auth/login",
            json={
                "email": "tiertest@example.com",
                "password": "testpass",
            },
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        assert payload is not None
        assert payload.org_id == org.id
        assert payload.subscription_tier == "pro"


class TestRegisterCreatesOrg:
    """Register endpoint should create a default org for new users."""

    @pytest.mark.asyncio
    async def test_register_creates_org_and_membership(self, client, db_session):
        resp = await client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "testpass123",
                "full_name": "New User",
            },
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        assert payload is not None
        assert payload.org_id is not None
        assert payload.subscription_tier == "essentials"


class TestOrgResponseIncludesTier:
    """Organization API responses should include subscription_tier."""

    @pytest.mark.asyncio
    async def test_org_list_includes_tier(
        self,
        client,
        auth_headers,
        test_org,
    ):
        resp = await client.get(
            f"/iam/organizations/{test_org.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "subscription_tier" in data
        assert data["subscription_tier"] == "essentials"


class TestAuthMiddleware:
    """AuthMiddleware should enforce authentication on protected routes."""

    @pytest.mark.asyncio
    async def test_public_route_no_auth_required(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_route_returns_401_without_token(self, client):
        resp = await client.get("/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_returns_401_with_invalid_token(self, client):
        resp = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_works_with_valid_token(
        self,
        client,
        auth_headers,
    ):
        resp = await client.get("/auth/me", headers=auth_headers)
        assert resp.status_code == 200


class TestRequireTier:
    """require_tier() dependency should gate endpoints by subscription tier."""

    @pytest.mark.asyncio
    async def test_require_tier_concept(self, test_user, test_org):
        """Verify that require_tier can compare tiers correctly."""
        from app.models.iam import TIER_RANK

        # Essentials tier user should be below pro
        current = SubscriptionTier(test_org.subscription_tier)
        assert TIER_RANK[current] < TIER_RANK[SubscriptionTier.PRO]

        # Essentials tier user should pass essentials check
        assert TIER_RANK[current] >= TIER_RANK[SubscriptionTier.ESSENTIALS]

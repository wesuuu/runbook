"""Tests for F-0035: Registration & Invitation Org Membership Flow.

Covers: switch-org, invitations (create/list/revoke/accept/decline),
org member removal with archived soft-delete, selected_org_id cascade,
and seed script org membership.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.iam import (Invitation, Organization, OrganizationMember, Team,
                            TeamMember, User)

# ---------- Fixtures ----------


@pytest.fixture
def _invitation_import():
    """Verify the Invitation model is importable."""
    from app.models.iam import Invitation

    return Invitation


# ---------- Switch Org ----------


class TestSwitchOrg:
    """POST /auth/switch-org"""

    @pytest.mark.asyncio
    async def test_switch_org_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """User with two org memberships can switch selected_org_id."""
        # Create second org and membership
        org2 = Organization(name="Second Org")
        db_session.add(org2)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=test_user.id,
                organization_id=org2.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.post(
            "/auth/switch-org",
            json={"org_id": str(org2.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

        # Verify user's selected_org_id updated in DB
        await db_session.refresh(test_user)
        assert test_user.selected_org_id == org2.id

    @pytest.mark.asyncio
    async def test_switch_org_not_member(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        """Switching to an org the user is not a member of returns 403."""
        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        await db_session.flush()

        resp = await client.post(
            "/auth/switch-org",
            json={"org_id": str(other_org.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_switch_org_returns_correct_jwt_claims(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """Returned JWT contains the new org_id and tier."""
        org2 = Organization(name="Pro Org", subscription_tier="pro")
        db_session.add(org2)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=test_user.id,
                organization_id=org2.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.post(
            "/auth/switch-org",
            json={"org_id": str(org2.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]

        # Use the new token to hit /auth/me — should work
        me_resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert me_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_switch_org_archived_membership_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
    ):
        """Cannot switch to an org where membership is archived."""
        org2 = Organization(name="Archived Org")
        db_session.add(org2)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=test_user.id,
                organization_id=org2.id,
                roles=["MEMBER"],
                archived=True,
            )
        )
        await db_session.flush()

        resp = await client.post(
            "/auth/switch-org",
            json={"org_id": str(org2.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 403


# ---------- Invitations: Admin Management ----------


class TestInvitationCreate:
    """POST /iam/organizations/{org_id}/invitations"""

    @pytest.mark.asyncio
    async def test_create_invitation_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
    ):
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "newuser@example.com", "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["invited_email"] == "newuser@example.com"
        assert data["status"] == "PENDING"
        assert data["organization_id"] == str(test_org.id)

    @pytest.mark.asyncio
    async def test_create_invitation_duplicate_409(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
    ):
        """Inviting the same email twice returns 409."""
        payload = {"email": "dupe@example.com", "role": "MEMBER"}
        resp1 = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json=payload,
            headers=auth_headers,
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json=payload,
            headers=auth_headers,
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_create_invitation_existing_member_409(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_user: User,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Inviting someone already a member returns 409."""
        # Add second_user to test_org
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email, "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_invitation_non_admin_403(
        self,
        client: AsyncClient,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Non-admin cannot create invitations."""
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        token = create_access_token(
            second_user.id,
            org_id=test_org.id,
            subscription_tier="essentials",
        )
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "invite@example.com"},
            headers=headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_invitation_links_existing_user(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
    ):
        """When inviting an email that matches an existing user,
        invited_user_id is populated."""
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email, "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["invited_user_id"] == str(second_user.id)


class TestInvitationList:
    """GET /iam/organizations/{org_id}/invitations"""

    @pytest.mark.asyncio
    async def test_list_org_invitations(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
    ):
        # Create two invitations
        for email in ["a@example.com", "b@example.com"]:
            await client.post(
                f"/iam/organizations/{test_org.id}/invitations",
                json={"email": email},
                headers=auth_headers,
            )

        resp = await client.get(
            f"/iam/organizations/{test_org.id}/invitations",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2


class TestInvitationRevoke:
    """DELETE /iam/invitations/{invitation_id}"""

    @pytest.mark.asyncio
    async def test_revoke_invitation(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
    ):
        # Create then revoke
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "revokeme@example.com"},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/iam/invitations/{invitation_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_revoked_invitation_accept_fails(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """After revoking, the accept link should no longer work."""
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "revoked@example.com"},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        await client.delete(
            f"/iam/invitations/{invitation_id}",
            headers=auth_headers,
        )

        # Get the invitation token from DB
        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()

        resp = await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )
        # Should return error (400 or redirect to error page)
        assert resp.status_code in (400, 302)


# ---------- Invitations: User Flow ----------


class TestMyInvitations:
    """GET /iam/me/invitations"""

    @pytest.mark.asyncio
    async def test_list_my_invitations(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
        test_org: Organization,
        second_user: User,
    ):
        """Invited user can see their pending invitations."""
        # Admin invites second_user's email
        await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email},
            headers=auth_headers,
        )

        resp = await client.get(
            "/iam/me/invitations",
            headers=second_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["invited_email"] == second_user.email


class TestAcceptInvitation:
    """GET /auth/accept-invite?token=xxx"""

    @pytest.mark.asyncio
    async def test_accept_invitation_existing_user(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Existing user accepts invitation → org membership created."""
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email, "role": "MEMBER"},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        invitation_id = create_resp.json()["id"]

        # Get token from DB
        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()

        resp = await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )
        # Should redirect to frontend
        assert resp.status_code == 302

        # Verify membership created
        result = await db_session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == second_user.id,
                OrganizationMember.organization_id == test_org.id,
                OrganizationMember.archived == False,
            )
        )
        membership = result.scalar_one_or_none()
        assert membership is not None
        assert "MEMBER" in (membership.roles or [])

    @pytest.mark.asyncio
    async def test_accept_invitation_no_account_redirects_to_register(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """Unknown email accepts → redirect to registration page."""
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "newperson@example.com"},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        invitation_id = create_resp.json()["id"]

        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()

        resp = await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "register" in location.lower()
        assert invitation.token in location

    @pytest.mark.asyncio
    async def test_accept_invitation_selected_org_stays(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        second_org: Organization,
        db_session: AsyncSession,
    ):
        """When user already has a selected_org, accepting an invite
        does NOT change it (AC #6 — no silent switch)."""
        assert second_user.selected_org_id == second_org.id

        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()

        await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )

        await db_session.refresh(second_user)
        assert second_user.selected_org_id == second_org.id

    @pytest.mark.asyncio
    async def test_accept_invitation_sets_selected_org_if_null(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """If user has selected_org_id=None, accepting sets it."""
        orphan = User(
            email="orphan@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Orphan User",
            selected_org_id=None,
            email_verified=True,
        )
        db_session.add(orphan)
        await db_session.flush()

        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": orphan.email},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()

        await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )

        await db_session.refresh(orphan)
        assert orphan.selected_org_id == test_org.id

    @pytest.mark.asyncio
    async def test_accept_expired_invitation_fails(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Expired invitation cannot be accepted."""
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        # Manually expire the invitation
        result = await db_session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        invitation = result.scalar_one()
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.flush()

        resp = await client.get(
            f"/auth/accept-invite?token={invitation.token}",
            follow_redirects=False,
        )
        assert resp.status_code in (400, 302)


class TestDeclineInvitation:
    """POST /iam/invitations/{invitation_id}/decline"""

    @pytest.mark.asyncio
    async def test_decline_invitation(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
        test_org: Organization,
        second_user: User,
    ):
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": second_user.email},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        resp = await client.post(
            f"/iam/invitations/{invitation_id}/decline",
            headers=second_auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_decline_by_wrong_user_403(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """Only the invited user can decline their invitation."""
        create_resp = await client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": "other@example.com"},
            headers=auth_headers,
        )
        invitation_id = create_resp.json()["id"]

        # Create a different user and try to decline
        other = User(
            email="intruder@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Intruder",
            email_verified=True,
        )
        db_session.add(other)
        await db_session.flush()

        other_org = Organization(name="Intruder Org")
        db_session.add(other_org)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=other.id,
                organization_id=other_org.id,
                roles=["MEMBER", "ADMIN"],
            )
        )
        await db_session.flush()

        token = create_access_token(other.id, org_id=other_org.id)
        resp = await client.post(
            f"/iam/invitations/{invitation_id}/decline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


# ---------- Remove Org Member (Soft Delete) ----------


class TestRemoveOrgMember:
    """DELETE /iam/organizations/{org_id}/members/{user_id}"""

    @pytest.mark.asyncio
    async def test_remove_member_archives_not_deletes(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Removing a member sets archived=True instead of deleting."""
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.delete(
            f"/iam/organizations/{test_org.id}/members/{second_user.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Row still exists but is archived
        result = await db_session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == second_user.id,
                OrganizationMember.organization_id == test_org.id,
            )
        )
        membership = result.scalar_one()
        assert membership.archived is True

    @pytest.mark.asyncio
    async def test_remove_member_cascades_selected_org(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """When removed from selected org, selected_org_id cascades
        to earliest remaining org."""
        # Create user with two orgs
        org2 = Organization(name="Fallback Org")
        db_session.add(org2)
        await db_session.flush()

        user = User(
            email="cascadetest@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Cascade User",
            selected_org_id=test_org.id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        # Membership in test_org (will be removed)
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        # Membership in org2 (fallback)
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=org2.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.delete(
            f"/iam/organizations/{test_org.id}/members/{user.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.selected_org_id == org2.id

    @pytest.mark.asyncio
    async def test_remove_from_last_org_nulls_selected_org(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """Removing from last org sets selected_org_id to None."""
        user = User(
            email="lastorg@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Last Org User",
            selected_org_id=test_org.id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        resp = await client.delete(
            f"/iam/organizations/{test_org.id}/members/{user.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.selected_org_id is None

    @pytest.mark.asyncio
    async def test_archived_member_not_in_member_list(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Archived members should not appear in GET /members."""
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        # Remove (archive) the member
        await client.delete(
            f"/iam/organizations/{test_org.id}/members/{second_user.id}",
            headers=auth_headers,
        )

        resp = await client.get(
            f"/iam/organizations/{test_org.id}/members",
            headers=auth_headers,
        )
        member_ids = [m["user_id"] for m in resp.json()]
        assert str(second_user.id) not in member_ids

    @pytest.mark.asyncio
    async def test_team_memberships_intact_after_org_removal(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_team: Team,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Team memberships remain after org removal (for reinstatement)."""
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        db_session.add(
            TeamMember(
                user_id=second_user.id,
                team_id=test_team.id,
                role="MEMBER",
            )
        )
        await db_session.flush()

        await client.delete(
            f"/iam/organizations/{test_org.id}/members/{second_user.id}",
            headers=auth_headers,
        )

        result = await db_session.execute(
            select(TeamMember).where(
                TeamMember.user_id == second_user.id,
                TeamMember.team_id == test_team.id,
            )
        )
        assert result.scalar_one_or_none() is not None


# ---------- Add Org Member (Reactivation) ----------


class TestAddOrgMember:
    """POST /iam/organizations/{org_id}/members"""

    @pytest.mark.asyncio
    async def test_readd_archived_member_reactivates(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        db_session: AsyncSession,
    ):
        """Re-adding an archived member reactivates them."""
        db_session.add(
            OrganizationMember(
                user_id=second_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
                archived=True,
            )
        )
        await db_session.flush()

        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(second_user.id), "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == second_user.id,
                OrganizationMember.organization_id == test_org.id,
            )
        )
        membership = result.scalar_one()
        assert membership.archived is False

    @pytest.mark.asyncio
    async def test_add_member_sets_selected_org_if_null(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        """Adding a member with no selected_org sets it to this org."""
        user = User(
            email="noorg@example.com",
            hashed_password=hash_password("testpass"),
            full_name="No Org User",
            selected_org_id=None,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(user.id), "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)

        await db_session.refresh(user)
        assert user.selected_org_id == test_org.id

    @pytest.mark.asyncio
    async def test_add_member_does_not_change_existing_selected_org(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        second_user: User,
        second_org: Organization,
        db_session: AsyncSession,
    ):
        """Adding to a new org does NOT change their selected_org_id."""
        assert second_user.selected_org_id == second_org.id

        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(second_user.id), "role": "MEMBER"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)

        await db_session.refresh(second_user)
        assert second_user.selected_org_id == second_org.id


# ---------- Archived Filtering ----------


class TestArchivedFiltering:
    """Archived memberships should be excluded from org queries."""

    @pytest.mark.asyncio
    async def test_archived_member_excluded_from_org_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """GET /iam/organizations should not return orgs
        where the user's membership is archived."""
        org = Organization(name="Archived Org")
        db_session.add(org)
        await db_session.flush()

        user = User(
            email="archivedlist@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Archived List User",
            selected_org_id=org.id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=org.id,
                roles=["MEMBER", "ADMIN"],
                archived=True,
            )
        )
        await db_session.flush()

        token = create_access_token(user.id, org_id=org.id)
        resp = await client.get(
            "/iam/organizations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        org_ids = [o["id"] for o in resp.json()]
        assert str(org.id) not in org_ids


# ---------- Seed Script ----------


class TestSeedOrgMembership:
    """All seed users must have selected_org_id set."""

    @pytest.mark.asyncio
    async def test_seed_users_have_selected_org(self):
        """Verify the seed script sets selected_org_id for all users."""
        from app.db.seed import (ORG_ID, USER_ADMIN, USER_DOWNSTREAM_LEAD,
                                 USER_SCIENTIST1, USER_SCIENTIST2,
                                 USER_UPSTREAM_LEAD, USER_VIEWER, seed_org,
                                 seed_users)
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await seed_users(db)
            await seed_org(db)
            await db.commit()

            for user_id in [
                USER_ADMIN,
                USER_UPSTREAM_LEAD,
                USER_DOWNSTREAM_LEAD,
                USER_SCIENTIST1,
                USER_SCIENTIST2,
                USER_VIEWER,
            ]:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user is not None:
                    assert (
                        user.selected_org_id is not None
                    ), f"Seed user {user_id} has no selected_org_id"


# ---------- Registration (Existing AC #1 — verify still works) ----------


class TestRegistrationOrgMembership:
    """Registration creates org + membership + selected_org_id in one tx."""

    @pytest.mark.asyncio
    async def test_register_creates_org_and_membership(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        resp = await client.post(
            "/auth/register",
            json={
                "email": "fresh@example.com",
                "password": "securepass123",
                "full_name": "Fresh User",
            },
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(User).where(User.email == "fresh@example.com")
        )
        user = result.scalar_one()
        assert user.selected_org_id is not None

        # Verify org membership exists
        result = await db_session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == user.selected_org_id,
                OrganizationMember.archived == False,
            )
        )
        membership = result.scalar_one()
        assert "ADMIN" in (membership.roles or [])

        # Verify org name
        result = await db_session.execute(
            select(Organization).where(Organization.id == user.selected_org_id)
        )
        org = result.scalar_one()
        assert org.name == "Fresh User's Organization"


class TestMultiRoleEndpoints:
    """TD-0084: IAM endpoints accept `roles: list[str]` payloads."""

    @pytest.mark.asyncio
    async def test_add_member_with_multi_roles(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        u = User(email="newmem@example.com", full_name="N")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={
                "user_id": str(u.id),
                "roles": ["BILLING", "PROTOCOL_APPROVER"],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "MEMBER" in body["roles"]
        assert "BILLING" in body["roles"]
        assert "PROTOCOL_APPROVER" in body["roles"]

    @pytest.mark.asyncio
    async def test_back_compat_shim_accepts_role_string(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
        caplog,
    ):
        import logging

        caplog.set_level(logging.WARNING, logger="app.deprecation")
        u = User(email="shim@example.com", full_name="S")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(u.id), "role": "BILLING"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert "BILLING" in resp.json()["roles"]
        assert "MEMBER" in resp.json()["roles"]
        assert any(
            "deprecated" in rec.message.lower() and "role" in rec.message.lower()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_validation_rejects_unknown_role(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        u = User(email="bad@example.com", full_name="B")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(u.id), "roles": ["BOGUS"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "BOGUS" in resp.text

    @pytest.mark.asyncio
    async def test_cannot_remove_last_admin(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        test_user: User,
    ):
        # test_user is the only ADMIN in test_org; downgrading to MEMBER-only
        # must fail with 400.
        resp = await client.patch(
            f"/iam/organizations/{test_org.id}/members/{test_user.id}",
            json={"roles": ["MEMBER"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400, resp.text
        assert "last admin" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_member_role_cannot_be_removed(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_org: Organization,
        db_session: AsyncSession,
    ):
        u = User(email="alwaysmem@example.com", full_name="A")
        db_session.add(u)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=u.id,
                organization_id=test_org.id,
                roles=["MEMBER", "BILLING"],
            )
        )
        await db_session.flush()

        resp = await client.patch(
            f"/iam/organizations/{test_org.id}/members/{u.id}",
            json={"roles": []},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["roles"] == ["MEMBER"]

"""Integration tests for notification API endpoints."""

from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.notifications import (
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
)

# ── Org Channel CRUD ─────────────────────────────────────────────────────


class TestOrgChannels:
    @pytest.mark.asyncio
    async def test_create_org_channel(self, client, auth_headers, test_org):
        resp = await client.post(
            "/notifications/channels",
            json={
                "name": "Wet Lab Slack",
                "channel_type": "CONSOLE",
                "config": {},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Wet Lab Slack"
        assert data["channel_type"] == "CONSOLE"
        assert data["org_id"] is not None
        assert data["user_id"] is None

    @pytest.mark.asyncio
    async def test_create_channel_invalid_type(self, client, auth_headers, test_org):
        resp = await client.post(
            "/notifications/channels",
            json={"name": "Bad", "channel_type": "PIGEON", "config": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_org_channels(self, client, auth_headers, test_org):
        # Create two channels
        await client.post(
            "/notifications/channels",
            json={"name": "Ch1", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        await client.post(
            "/notifications/channels",
            json={
                "name": "Ch2",
                "channel_type": "WEBHOOK",
                "config": {"url": "http://test"},
            },
            headers=auth_headers,
        )

        resp = await client.get("/notifications/channels", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    @pytest.mark.asyncio
    async def test_update_org_channel(self, client, auth_headers, test_org):
        create_resp = await client.post(
            "/notifications/channels",
            json={"name": "Old Name", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = create_resp.json()["id"]

        resp = await client.put(
            f"/notifications/channels/{channel_id}",
            json={"name": "New Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_delete_org_channel(self, client, auth_headers, test_org):
        create_resp = await client.post(
            "/notifications/channels",
            json={"name": "To Delete", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/notifications/channels/{channel_id}", headers=auth_headers
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_org_channel(
        self, client, test_org, db_session
    ):
        """A MEMBER (not ADMIN) of an org should not be able to create
        org-level notification channels."""
        from app.core.security import create_access_token, hash_password
        from app.models.iam import OrganizationMember, User

        member = User(
            email="member_only@example.com",
            hashed_password=hash_password("testpass"),
            full_name="Member Only",
            selected_org_id=test_org.id,
        )
        db_session.add(member)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=member.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
            )
        )
        await db_session.flush()

        token = create_access_token(
            member.id,
            org_id=test_org.id,
            subscription_tier=test_org.subscription_tier,
        )
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/notifications/channels",
            json={"name": "Nope", "channel_type": "CONSOLE", "config": {}},
            headers=headers,
        )
        assert resp.status_code in (400, 403)


# ── User Channel CRUD ────────────────────────────────────────────────────


class TestUserChannels:
    @pytest.mark.asyncio
    async def test_create_user_channel(self, client, auth_headers):
        resp = await client.post(
            "/notifications/channels/me",
            json={
                "name": "My Discord",
                "channel_type": "DISCORD",
                "config": {"webhook_url": "https://discord.com/api/webhooks/test"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] is not None
        assert data["org_id"] is None
        assert data["name"] == "My Discord"

    @pytest.mark.asyncio
    async def test_list_user_channels(self, client, auth_headers):
        await client.post(
            "/notifications/channels/me",
            json={"name": "My Slack", "channel_type": "SLACK", "config": {}},
            headers=auth_headers,
        )

        resp = await client.get("/notifications/channels/me", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_other_user_cannot_update(
        self, client, auth_headers, second_auth_headers
    ):
        create_resp = await client.post(
            "/notifications/channels/me",
            json={"name": "Private", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = create_resp.json()["id"]

        resp = await client.put(
            f"/notifications/channels/me/{channel_id}",
            json={"name": "Hacked"},
            headers=second_auth_headers,
        )
        assert resp.status_code == 403


# ── Subscriptions ────────────────────────────────────────────────────────


class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_create_subscription(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "Sub Test", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        resp = await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "RUN_STARTED"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["event_type"] == "RUN_STARTED"
        assert resp.json()["enabled"] is True

    @pytest.mark.asyncio
    async def test_duplicate_subscription_updates(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "Dup Test", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        # Create
        await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "RUN_COMPLETED", "enabled": True},
            headers=auth_headers,
        )

        # Duplicate with different enabled value — should update
        resp = await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "RUN_COMPLETED", "enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["enabled"] is False

    @pytest.mark.asyncio
    async def test_invalid_event_type(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "Inv Test", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        resp = await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "MOON_LANDING"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_subscriptions(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "List Sub", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "RUN_STARTED"},
            headers=auth_headers,
        )
        await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "ROLE_ASSIGNED"},
            headers=auth_headers,
        )

        resp = await client.get(
            f"/notifications/channels/{channel_id}/subscriptions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_delete_subscription(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "Del Sub", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        sub_resp = await client.post(
            f"/notifications/channels/{channel_id}/subscriptions",
            json={"event_type": "RUN_STARTED"},
            headers=auth_headers,
        )
        sub_id = sub_resp.json()["id"]

        resp = await client.delete(
            f"/notifications/channels/{channel_id}/subscriptions/{sub_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204


# ── In-App Notifications ────────────────────────────────────────────────


class TestInAppNotifications:
    @pytest.mark.asyncio
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get(
            "/notifications/?include_total=true", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_unread_count_empty(self, client, auth_headers):
        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_create_and_read_notification(
        self, client, auth_headers, test_user, db_session
    ):
        # Manually insert a notification
        notif = Notification(
            user_id=test_user.id,
            event_type="RUN_STARTED",
            entity_type="run",
            entity_id=uuid4(),
            title="Run started",
            message="Run CHO-042 started by Alice",
        )
        db_session.add(notif)
        await db_session.flush()

        # List (include_total so the count is populated)
        resp = await client.get(
            "/notifications/?include_total=true", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Run started"
        assert data["items"][0]["read_at"] is None

        # Unread count
        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.json()["count"] == 1

        # Mark read
        notif_id = data["items"][0]["id"]
        resp = await client.put(f"/notifications/{notif_id}/read", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["read_at"] is not None

        # Unread count should be 0
        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_mark_all_read(self, client, auth_headers, test_user, db_session):
        for i in range(3):
            db_session.add(
                Notification(
                    user_id=test_user.id,
                    event_type="RUN_STARTED",
                    entity_type="run",
                    entity_id=uuid4(),
                    title=f"Notif {i}",
                    message=f"Message {i}",
                )
            )
        await db_session.flush()

        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.json()["count"] == 3

        resp = await client.put("/notifications/read-all", headers=auth_headers)
        assert resp.status_code == 204

        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_cannot_read_other_users_notification(
        self, client, second_auth_headers, test_user, db_session
    ):
        notif = Notification(
            user_id=test_user.id,
            event_type="RUN_STARTED",
            entity_type="run",
            entity_id=uuid4(),
            title="Private",
            message="Not yours",
        )
        db_session.add(notif)
        await db_session.flush()

        resp = await client.put(
            f"/notifications/{notif.id}/read", headers=second_auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_total_omitted_by_default(
        self, client, auth_headers, test_user, db_session
    ):
        """Without include_total the count is skipped — total is 0 even
        though items are returned."""
        for i in range(2):
            db_session.add(
                Notification(
                    user_id=test_user.id,
                    event_type="RUN_STARTED",
                    entity_type="run",
                    entity_id=uuid4(),
                    title=f"Notif {i}",
                    message=f"Message {i}",
                )
            )
        await db_session.flush()

        resp = await client.get("/notifications/", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_total_included_when_requested(
        self, client, auth_headers, test_user, db_session
    ):
        """include_total=true runs the COUNT and returns the real total."""
        for i in range(3):
            db_session.add(
                Notification(
                    user_id=test_user.id,
                    event_type="RUN_STARTED",
                    entity_type="run",
                    entity_id=uuid4(),
                    title=f"Notif {i}",
                    message=f"Message {i}",
                )
            )
        await db_session.flush()

        resp = await client.get(
            "/notifications/?include_total=true&limit=2", headers=auth_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2  # limited
        assert data["total"] == 3  # full count

    @pytest.mark.asyncio
    async def test_list_resolves_deep_link_url_for_run(
        self, client, auth_headers, db_session, test_user, test_project
    ):
        from app.models.notifications import Notification
        from app.models.runs import Run

        run = Run(name="CHO 7", slug="cho-7", project_id=test_project.id)
        db_session.add(run)
        await db_session.flush()
        db_session.add(
            Notification(
                user_id=test_user.id,
                event_type="RUN_STARTED",
                entity_type="run",
                entity_id=run.id,
                title="Run started",
                message="CHO-7 started",
            )
        )
        await db_session.commit()

        resp = await client.get("/notifications/", headers=auth_headers)

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["url"] == (
            "/test-org/projects/test-project/runs/cho-7"
        )

    @pytest.mark.asyncio
    async def test_list_url_is_null_for_unroutable_entity(
        self, client, auth_headers, db_session, test_user
    ):
        from uuid import uuid4

        from app.models.notifications import Notification

        db_session.add(
            Notification(
                user_id=test_user.id,
                event_type="INVITE_SENT",
                entity_type="RevokedOfflineToken",
                entity_id=uuid4(),
                title="x",
                message="y",
            )
        )
        await db_session.commit()

        resp = await client.get("/notifications/", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["items"][0]["url"] is None

    @pytest.mark.asyncio
    async def test_mark_read_returns_resolved_url(
        self, client, auth_headers, db_session, test_user, test_project
    ):
        from app.models.notifications import Notification
        from app.models.runs import Run

        run = Run(name="CHO 8", slug="cho-8", project_id=test_project.id)
        db_session.add(run)
        await db_session.flush()
        notif = Notification(
            user_id=test_user.id,
            event_type="RUN_STARTED",
            entity_type="run",
            entity_id=run.id,
            title="Run started",
            message="CHO-8 started",
        )
        db_session.add(notif)
        await db_session.commit()

        resp = await client.put(
            f"/notifications/{notif.id}/read", headers=auth_headers
        )

        assert resp.status_code == 200
        assert resp.json()["url"] == (
            "/test-org/projects/test-project/runs/cho-8"
        )


# ── Channel Test Endpoint ────────────────────────────────────────────────


class TestChannelTest:
    @pytest.mark.asyncio
    async def test_test_console_channel(self, client, auth_headers, test_org):
        ch_resp = await client.post(
            "/notifications/channels",
            json={"name": "Console Test", "channel_type": "CONSOLE", "config": {}},
            headers=auth_headers,
        )
        channel_id = ch_resp.json()["id"]

        resp = await client.post(
            f"/notifications/channels/{channel_id}/test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SENT"
        assert data["detail"] == "logged"


# ── Fix 4: _get_user_org_id honors selected_org_id ───────────────────────


class TestOrgResolution:
    """A multi-org user's channels/deliveries resolve to selected_org_id."""

    async def _make_multi_org_user(
        self,
        db_session,
        email,
        first_org,
        second_org,
        selected_org_id,
        first_org_roles=("MEMBER", "ADMIN"),
        second_org_roles=("MEMBER", "ADMIN"),
    ):
        """Create a user who joins first_org then second_org, with the given
        selected_org_id and per-org roles. Returns auth headers.

        Both memberships are inserted inside one transaction, so PostgreSQL's
        transaction-fixed now() stamps them with the *same* created_at —
        there is no "older" membership. Every test using this helper sets a
        valid selected_org_id, so _get_user_org_id resolves via the
        selected-org re-check and never reaches the created_at fallback; the
        fallback tie-break is therefore not exercised here.
        """
        from app.core.security import create_access_token, hash_password
        from app.models.iam import OrganizationMember, User

        user = User(
            email=email,
            hashed_password=hash_password("testpass"),
            full_name="Multi Org User",
            selected_org_id=selected_org_id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=first_org.id,
                roles=list(first_org_roles),
            )
        )
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=second_org.id,
                roles=list(second_org_roles),
            )
        )
        await db_session.flush()
        token = create_access_token(
            user.id,
            org_id=selected_org_id or first_org.id,
            subscription_tier=first_org.subscription_tier,
            email_verified=True,
        )
        return {"Authorization": f"Bearer {token}"}

    async def _make_single_org_user(
        self, db_session, email, org, selected_org_id,
        roles=("MEMBER", "ADMIN"),
    ):
        """Create a single-org user with the given selected_org_id — which
        may intentionally point at an org they do NOT belong to. Returns
        auth headers. Shared by the two fallback regression-guard tests so
        they do not inline duplicated user-creation."""
        from app.core.security import create_access_token, hash_password
        from app.models.iam import OrganizationMember, User

        user = User(
            email=email,
            hashed_password=hash_password("testpass"),
            full_name="Single Org User",
            selected_org_id=selected_org_id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=org.id,
                roles=list(roles),
            )
        )
        await db_session.flush()
        token = create_access_token(
            user.id,
            org_id=org.id,
            subscription_tier=org.subscription_tier,
            email_verified=True,
        )
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_list_channels_honors_selected_org_id(
        self, client, test_org, second_org, db_session
    ):
        """selected_org_id points at the SECOND org => list its channels,
        not the first membership's."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="First Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        db_session.add(
            NotificationChannel(
                org_id=second_org.id, name="Second Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_multi_org_user(
            db_session, "multiorg1@example.com", test_org, second_org,
            selected_org_id=second_org.id,
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Second Org Ch"}

    @pytest.mark.asyncio
    async def test_list_deliveries_honors_selected_org_id(
        self, client, test_org, second_org, db_session
    ):
        """A multi-org admin sees the selected org's delivery log."""
        second_channel = NotificationChannel(
            org_id=second_org.id, name="Second Org Ch",
            channel_type="CONSOLE", config={},
        )
        db_session.add(second_channel)
        await db_session.flush()
        db_session.add(
            NotificationDelivery(
                channel_id=second_channel.id,
                event_type="RUN_STARTED",
                recipient_info={"recipient": "x@example.com"},
                status="SENT",
                attempts=1,
            )
        )
        await db_session.flush()
        headers = await self._make_multi_org_user(
            db_session, "multiorg2@example.com", test_org, second_org,
            selected_org_id=second_org.id,
        )
        resp = await client.get("/notifications/deliveries", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_create_channel_admin_check_uses_selected_org(
        self, client, test_org, second_org, db_session
    ):
        """User is only a MEMBER of their first org but an ADMIN of the
        selected (second) org. Before the fix, _get_user_org_id resolves to
        the first org and _require_org_admin returns 403; after the fix it
        resolves to the selected org and the create succeeds (201)."""
        headers = await self._make_multi_org_user(
            db_session, "multiadmin1@example.com", test_org, second_org,
            selected_org_id=second_org.id,
            first_org_roles=("MEMBER",),
            second_org_roles=("MEMBER", "ADMIN"),
        )
        resp = await client.post(
            "/notifications/channels",
            json={"name": "Sel Org Ch", "channel_type": "CONSOLE",
                  "config": {}},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["org_id"] == str(second_org.id)

    @pytest.mark.asyncio
    async def test_list_deliveries_admin_check_uses_selected_org(
        self, client, test_org, second_org, db_session
    ):
        """Same MEMBER-of-first / ADMIN-of-selected user: the admin-gated
        deliveries log resolves to the selected org and returns 200, not the
        403 the first-membership resolution would produce."""
        headers = await self._make_multi_org_user(
            db_session, "multiadmin2@example.com", test_org, second_org,
            selected_org_id=second_org.id,
            first_org_roles=("MEMBER",),
            second_org_roles=("MEMBER", "ADMIN"),
        )
        resp = await client.get(
            "/notifications/deliveries", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_fallback_when_selected_org_id_unset(
        self, client, test_org, db_session
    ):
        """A single-org user with selected_org_id=None resolves to their
        one membership (regression guard)."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="Only Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_single_org_user(
            db_session, "noselected@example.com", test_org,
            selected_org_id=None,
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Only Org Ch"}

    @pytest.mark.asyncio
    async def test_stale_selected_org_id_falls_back(
        self, client, test_org, second_org, db_session
    ):
        """selected_org_id points at an org the user does NOT belong to =>
        fall back to a real membership; no 403, no cross-org leak."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="Real Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        db_session.add(
            NotificationChannel(
                org_id=second_org.id, name="Other Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_single_org_user(
            db_session, "staleselected@example.com", test_org,
            selected_org_id=second_org.id,  # not a member of second_org
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Real Org Ch"}

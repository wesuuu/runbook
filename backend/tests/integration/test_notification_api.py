"""Integration tests for notification API endpoints."""

import pytest
import pytest_asyncio
from uuid import uuid4

from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
    Notification,
    NotificationDelivery,
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
            json={"name": "Ch2", "channel_type": "WEBHOOK", "config": {"url": "http://test"}},
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
        self, client, second_auth_headers, test_org
    ):
        resp = await client.post(
            "/notifications/channels",
            json={"name": "Nope", "channel_type": "CONSOLE", "config": {}},
            headers=second_auth_headers,
        )
        # second_user is not in the org, so should fail
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
        resp = await client.get("/notifications/", headers=auth_headers)
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

        # List
        resp = await client.get("/notifications/", headers=auth_headers)
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
        resp = await client.put(
            f"/notifications/{notif_id}/read", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["read_at"] is not None

        # Unread count should be 0
        resp = await client.get("/notifications/unread-count", headers=auth_headers)
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_mark_all_read(
        self, client, auth_headers, test_user, db_session
    ):
        for i in range(3):
            db_session.add(Notification(
                user_id=test_user.id,
                event_type="RUN_STARTED",
                entity_type="run",
                entity_id=uuid4(),
                title=f"Notif {i}",
                message=f"Message {i}",
            ))
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

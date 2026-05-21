from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_verification_jwt,
    decode_access_token,
    hash_password,
)
from app.models.iam import User, VerificationToken

# ---------- register ----------


@pytest.mark.asyncio
async def test_register_returns_verification_token(client: AsyncClient):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "securepass",
                "full_name": "New User",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "verification_token" in data
    assert "access_token" not in data
    assert data["message"] == "Check your email to verify your account"

    # Decode the temp JWT — should have scope=verification
    payload = decode_access_token(data["verification_token"])
    assert payload is not None
    assert payload.scope == "verification"


@pytest.mark.asyncio
async def test_register_seeds_first_project(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from app.models.iam import Organization
    from app.models.projects import Project

    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "seeded@example.com",
                "password": "securepass",
                "full_name": "Seeded User",
            },
        )
    assert resp.status_code == 200

    # Find the newly-created org (by name pattern) and its project.
    org_result = await db_session.execute(
        select(Organization).where(Organization.name == "Seeded User's Organization")
    )
    org = org_result.scalar_one()

    proj_result = await db_session.execute(
        select(Project).where(Project.organization_id == org.id)
    )
    projects = proj_result.scalars().all()
    assert len(projects) == 1
    assert projects[0].name == "My First Project"
    # F-0091: the seeded project must get a slug for GitHub-style routes.
    assert projects[0].slug


@pytest.mark.asyncio
async def test_register_duplicate_email(
    client: AsyncClient,
    test_user: User,
):
    resp = await client.post(
        "/auth/register",
        json={
            "email": test_user.email,
            "password": "anything",
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_sends_verification_email(client: AsyncClient):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_instance = AsyncMock()
        mock_provider.return_value = mock_instance

        await client.post(
            "/auth/register",
            json={
                "email": "emailtest@example.com",
                "password": "securepass",
            },
        )

    mock_instance.send.assert_called_once()
    call_kwargs = mock_instance.send.call_args
    assert call_kwargs[1]["to"] == "emailtest@example.com"
    assert "verify-email" in call_kwargs[1]["html_body"]
    assert "token=" in call_kwargs[1]["html_body"]


# ---------- verify email ----------


@pytest.mark.asyncio
async def test_verify_email_success(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "verify@example.com",
                "password": "securepass",
            },
        )

    # Get the token from DB
    result = await db_session.execute(
        select(VerificationToken)
        .where(VerificationToken.purpose == "email_verification")
        .order_by(VerificationToken.created_at.desc())
    )
    vt = result.scalars().first()
    assert vt is not None

    # Verify (returns 302 redirect to frontend with auth_token param)
    resp = await client.get(
        f"/auth/verify-email?token={vt.token}&email=verify@example.com",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "auth_token=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_verify_email_wrong_token(client: AsyncClient):
    resp = await client.get(
        "/auth/verify-email?token=bogustoken123&email=nobody@example.com"
    )
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_verify_email_expired_token(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        await client.post(
            "/auth/register",
            json={
                "email": "expired@example.com",
                "password": "securepass",
            },
        )

    # Manually expire the token
    result = await db_session.execute(
        select(VerificationToken).order_by(VerificationToken.created_at.desc())
    )
    vt = result.scalars().first()
    vt.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.get(
        f"/auth/verify-email?token={vt.token}&email=expired@example.com"
    )
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_verify_email_wrong_email(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        await client.post(
            "/auth/register",
            json={
                "email": "mismatch@example.com",
                "password": "securepass",
            },
        )

    result = await db_session.execute(
        select(VerificationToken).order_by(VerificationToken.created_at.desc())
    )
    vt = result.scalars().first()

    resp = await client.get(
        f"/auth/verify-email?token={vt.token}&email=wrong@example.com"
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_verify_email_already_used(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        await client.post(
            "/auth/register",
            json={
                "email": "used@example.com",
                "password": "securepass",
            },
        )

    result = await db_session.execute(
        select(VerificationToken).order_by(VerificationToken.created_at.desc())
    )
    vt = result.scalars().first()

    # Verify once (success — returns 302 redirect)
    resp = await client.get(
        f"/auth/verify-email?token={vt.token}&email=used@example.com",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # Try again (should fail — token is used)
    resp = await client.get(
        f"/auth/verify-email?token={vt.token}&email=used@example.com"
    )
    assert resp.status_code == 400


# ---------- resend verification ----------


@pytest.mark.asyncio
async def test_resend_verification_success(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_instance = AsyncMock()
        mock_provider.return_value = mock_instance

        resp = await client.post(
            "/auth/register",
            json={
                "email": "resend@example.com",
                "password": "securepass",
            },
        )
        temp_token = resp.json()["verification_token"]
        headers = {"Authorization": f"Bearer {temp_token}"}

        resp = await client.post("/auth/resend-verification", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Verification email sent"


@pytest.mark.asyncio
async def test_resend_verification_rate_limit(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "ratelimit@example.com",
                "password": "securepass",
            },
        )
        temp_token = resp.json()["verification_token"]
        headers = {"Authorization": f"Bearer {temp_token}"}

        # Register created 1 token. Resend 2 more to hit the limit of 3.
        await client.post("/auth/resend-verification", headers=headers)
        await client.post("/auth/resend-verification", headers=headers)

        # 4th attempt should be rate-limited
        resp = await client.post("/auth/resend-verification", headers=headers)
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_resend_already_verified(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
):
    # test_user is email_verified=True (grandfathered)
    resp = await client.post("/auth/resend-verification", headers=auth_headers)
    assert resp.status_code == 400
    assert "already verified" in resp.json()["detail"].lower()


# ---------- scope gating ----------


@pytest.mark.asyncio
async def test_verification_scope_blocks_protected(
    client: AsyncClient,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "gated@example.com",
                "password": "securepass",
            },
        )
        temp_token = resp.json()["verification_token"]
        headers = {"Authorization": f"Bearer {temp_token}"}

    # Should be blocked from protected endpoints
    resp = await client.get("/projects", headers=headers)
    assert resp.status_code == 403
    assert "not verified" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_verification_scope_allows_me(
    client: AsyncClient,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "metest@example.com",
                "password": "securepass",
            },
        )
        temp_token = resp.json()["verification_token"]
        headers = {"Authorization": f"Bearer {temp_token}"}

    resp = await client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email_verified"] is False


@pytest.mark.asyncio
async def test_verification_scope_allows_resend(
    client: AsyncClient,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        resp = await client.post(
            "/auth/register",
            json={
                "email": "resendok@example.com",
                "password": "securepass",
            },
        )
        temp_token = resp.json()["verification_token"]
        headers = {"Authorization": f"Bearer {temp_token}"}

        resp = await client.post("/auth/resend-verification", headers=headers)
    assert resp.status_code == 200


# ---------- login ----------


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user: User):
    resp = await client.post(
        "/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "testpass",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user: User):
    resp = await client.post(
        "/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "wrongpass",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient):
    resp = await client.post(
        "/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "anything",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unverified_user_gets_limited_token(
    client: AsyncClient,
    db_session: AsyncSession,
):
    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()

        await client.post(
            "/auth/register",
            json={
                "email": "unverified_login@example.com",
                "password": "securepass",
            },
        )

    # Login
    resp = await client.post(
        "/auth/login",
        json={
            "email": "unverified_login@example.com",
            "password": "securepass",
        },
    )
    assert resp.status_code == 200
    payload = decode_access_token(resp.json()["access_token"])
    assert payload is not None
    assert payload.email_verified is False


# ---------- me ----------


@pytest.mark.asyncio
async def test_me_authenticated(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
):
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "testuser@example.com"
    assert data["id"] == str(test_user.id)


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert resp.status_code == 401


# ---------- grandfathering ----------


@pytest.mark.asyncio
async def test_existing_users_grandfathered(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
):
    """test_user was created by conftest — should be email_verified=True."""
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email_verified"] is True


# ---------- preferences: theme ----------


@pytest.mark.asyncio
async def test_update_preferences_persists_theme(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    resp = await client.put(
        "/auth/me/preferences",
        json={"theme": "blueprint"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["preferences"]["theme"] == "blueprint"

    await db_session.refresh(test_user)
    assert test_user.preferences.get("theme") == "blueprint"


@pytest.mark.asyncio
async def test_update_preferences_rejects_unknown_theme(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.put(
        "/auth/me/preferences",
        json={"theme": "nope"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "theme" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_preferences_does_not_clobber_other_keys(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    await client.put(
        "/auth/me/preferences",
        json={"font_size": "large"},
        headers=auth_headers,
    )
    await client.put(
        "/auth/me/preferences",
        json={"theme": "apothecary"},
        headers=auth_headers,
    )
    await db_session.refresh(test_user)
    assert test_user.preferences.get("font_size") == "large"
    assert test_user.preferences.get("theme") == "apothecary"

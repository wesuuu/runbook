import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiProviderConfig
from app.models.iam import Organization, User


# --- Auth required ---


@pytest.mark.asyncio
async def test_list_settings_requires_auth(client: AsyncClient):
    resp = await client.get("/ai/settings")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upsert_setting_requires_auth(client: AsyncClient):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "ollama",
            "model_name": "llama3.2-vision",
            "is_enabled": True,
        },
    )
    assert resp.status_code == 401


# --- GET /ai/settings ---


@pytest.mark.asyncio
async def test_list_settings_empty(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.get("/ai/settings", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert "subscription_tier" in data


@pytest.mark.asyncio
async def test_list_settings_returns_configs(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        credentials={"base_url": "http://localhost:11434"},
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/ai/settings", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["capability"] == "vision"
    assert item["provider"] == "ollama"
    assert item["model_name"] == "llama3.2-vision"
    assert item["is_enabled"] is True
    assert item["credentials_set"] is True


@pytest.mark.asyncio
async def test_list_settings_credentials_not_exposed(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="vision",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        credentials={"api_key": "sk-ant-api03-abcdefghijklmnop"},
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/ai/settings", headers=auth_headers)
    item = resp.json()["items"][0]
    assert item["credentials_set"] is True
    # Credentials must NOT appear in response
    assert "credentials" not in item or item.get("credentials") is None
    assert "api_key" not in item
    assert "abcdefghijklmnop" not in str(item)


@pytest.mark.asyncio
async def test_list_settings_no_credentials(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/ai/settings", headers=auth_headers)
    item = resp.json()["items"][0]
    assert item["credentials_set"] is False


# --- PUT /ai/settings/{capability} ---


@pytest.mark.asyncio
async def test_upsert_creates_new_config(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "ollama",
            "model_name": "llama3.2-vision",
            "credentials": {"base_url": "http://localhost:11434"},
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["capability"] == "vision"
    assert data["provider"] == "ollama"
    assert data["credentials_set"] is True

    # Verify in DB
    result = await db_session.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.org_id == test_org.id,
            AiProviderConfig.capability == "vision",
        )
    )
    row = result.scalar_one()
    assert row.provider == "ollama"
    assert row.credentials == {"base_url": "http://localhost:11434"}


@pytest.mark.asyncio
async def test_upsert_updates_existing_config(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()
    original_id = str(row.id)

    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-20250514",
            "credentials": {"api_key": "sk-ant-test-key"},
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == original_id
    assert data["provider"] == "anthropic"


@pytest.mark.asyncio
async def test_upsert_rejects_unsupported_capability(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.put(
        "/ai/settings/telepathy",
        json={
            "provider": "ollama",
            "model_name": "mind-reader",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "Unsupported capability" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upsert_rejects_unsupported_provider(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "skynet",
            "model_name": "terminator-v1",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "Unsupported provider" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upsert_preserves_existing_credentials_when_not_provided(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="text",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        credentials={"api_key": "sk-ant-original-key"},
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    # Update without providing credentials — should keep old ones
    resp = await client.put(
        "/ai/settings/text",
        json={
            "provider": "anthropic",
            "model_name": "claude-opus-4-20250514",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(row)
    assert row.credentials == {"api_key": "sk-ant-original-key"}
    assert row.model_name == "claude-opus-4-20250514"


@pytest.mark.asyncio
async def test_upsert_ollama_does_not_require_credentials(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "ollama",
            "model_name": "llama3.2-vision",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200


# --- DELETE /ai/settings/{capability} ---


@pytest.mark.asyncio
async def test_delete_removes_config(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.delete("/ai/settings/vision", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify removed
    result = await db_session.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.org_id == test_org.id,
            AiProviderConfig.capability == "vision",
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_nonexistent_is_ok(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.delete("/ai/settings/vision", headers=auth_headers)
    assert resp.status_code == 200


# --- POST /ai/settings/{capability}/test ---


@pytest.mark.asyncio
async def test_test_connection_no_config_essentials_org(
    client: AsyncClient,
    auth_headers: dict,
):
    """Essentials org with no custom config should get 'not configured' error."""
    resp = await client.post(
        "/ai/settings/vision/test",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "not configured" in data["message"]


@pytest.mark.asyncio
async def test_test_connection_with_config_returns_result(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    """Org with a config should attempt a real connection test.
    With no actual provider running, it should return a connection failure."""
    row = AiProviderConfig(
        org_id=test_org.id,
        capability="text",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        credentials={"api_key": "sk-ant-test-key"},
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        "/ai/settings/text/test",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # With a fake API key and no real provider, this will fail
    # but the endpoint should handle it gracefully
    assert isinstance(data["success"], bool)
    assert isinstance(data["message"], str)


@pytest.mark.asyncio
async def test_test_connection_unsupported_capability(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.post(
        "/ai/settings/telepathy/test",
        headers=auth_headers,
    )
    assert resp.status_code == 422

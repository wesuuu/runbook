import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiProviderConfig
from app.models.iam import User
from app.services.ai_config import invalidate_cache, _cache


@pytest_asyncio.fixture(autouse=True)
async def clear_ai_cache():
    invalidate_cache()
    yield
    invalidate_cache()


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


@pytest.mark.asyncio
async def test_list_settings_returns_configs(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        api_key="sk-secret-key-12345678",
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


@pytest.mark.asyncio
async def test_list_settings_masks_api_key(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        capability="vision",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        api_key="sk-ant-api03-abcdefghijklmnop",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/ai/settings", headers=auth_headers)
    item = resp.json()["items"][0]
    assert item["api_key_set"] is True
    assert item["api_key_hint"] is not None
    # Full key must NOT appear
    assert "abcdefghijklmnop" not in item["api_key_hint"]
    # Should have masked format
    assert "..." in item["api_key_hint"]


@pytest.mark.asyncio
async def test_list_settings_no_key_set(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get("/ai/settings", headers=auth_headers)
    item = resp.json()["items"][0]
    assert item["api_key_set"] is False
    assert item["api_key_hint"] is None


# --- PUT /ai/settings/{capability} ---


@pytest.mark.asyncio
async def test_upsert_creates_new_config(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "ollama",
            "model_name": "llama3.2-vision",
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["capability"] == "vision"
    assert data["provider"] == "ollama"
    assert data["model_name"] == "llama3.2-vision"

    # Verify in DB
    result = await db_session.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == "vision"
        )
    )
    row = result.scalar_one()
    assert row.provider == "ollama"


@pytest.mark.asyncio
async def test_upsert_updates_existing_config(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    # Create initial config
    row = AiProviderConfig(
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()
    original_id = str(row.id)

    # Update it
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-20250514",
            "api_key": "sk-ant-test-key",
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == original_id  # Same row updated
    assert data["provider"] == "anthropic"
    assert data["model_name"] == "claude-sonnet-4-20250514"


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
async def test_upsert_cloud_provider_requires_api_key(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-20250514",
            # No api_key
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "requires an API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upsert_ollama_does_not_require_api_key(
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


@pytest.mark.asyncio
async def test_upsert_invalidates_cache(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    from app.services.ai_config import get_model

    # Prime cache with default (Ollama returns OpenAIModel object)
    model = await get_model("vision", db_session)
    assert model.model_name == "llama3.2-vision"
    assert "vision" in _cache

    # Update via API
    resp = await client.put(
        "/ai/settings/vision",
        json={
            "provider": "ollama",
            "model_name": "llava",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Cache should have been invalidated
    assert "vision" not in _cache


@pytest.mark.asyncio
async def test_upsert_preserves_existing_key_when_not_provided(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    # Create with API key
    row = AiProviderConfig(
        capability="text",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        api_key="sk-ant-original-key",
        is_enabled=True,
    )
    db_session.add(row)
    await db_session.flush()

    # Update without providing api_key — should keep old one
    resp = await client.put(
        "/ai/settings/text",
        json={
            "provider": "anthropic",
            "model_name": "claude-opus-4-20250514",
            # api_key omitted
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify key was preserved
    await db_session.refresh(row)
    assert row.api_key == "sk-ant-original-key"
    assert row.model_name == "claude-opus-4-20250514"


# --- POST /ai/settings/{capability}/test ---


@pytest.mark.asyncio
async def test_test_connection_no_config(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.post(
        "/ai/settings/vision/test",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "No configuration found" in data["message"]


@pytest.mark.asyncio
async def test_test_connection_disabled(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        capability="vision",
        provider="ollama",
        model_name="llama3.2-vision",
        is_enabled=False,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        "/ai/settings/vision/test",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "disabled" in data["message"]


@pytest.mark.asyncio
async def test_test_connection_cloud_with_key(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    row = AiProviderConfig(
        capability="text",
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        api_key="sk-ant-test-key",
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
    assert data["success"] is True
    assert "API key is set" in data["message"]


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

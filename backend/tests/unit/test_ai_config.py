import uuid

import pytest
import pytest_asyncio
from pydantic_ai.models.openai import OpenAIChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiProviderConfig
from app.models.iam import Organization, OrganizationMember, User
from app.core.security import hash_password
from app.core.config import ProviderConfig, settings
from app.services.ai_config import (
    _build_model_string,
    _get_env_fallback,
    get_model,
    get_full_config,
)


class TestBuildModelString:
    def test_ollama(self):
        result = _build_model_string("ollama", "llama3.2-vision")
        assert isinstance(result, OpenAIChatModel)
        assert result.model_name == "llama3.2-vision"

    def test_ollama_with_base_url(self):
        result = _build_model_string("ollama", "llama3.2-vision", credentials={"base_url": "http://myhost:11434"})
        assert isinstance(result, OpenAIChatModel)

    def test_anthropic(self):
        assert _build_model_string("anthropic", "claude-sonnet-4-20250514") == "anthropic:claude-sonnet-4-20250514"

    def test_google(self):
        assert _build_model_string("google", "gemini-2.0-flash") == "google-gla:gemini-2.0-flash"

    def test_openai(self):
        assert _build_model_string("openai", "gpt-4o") == "openai:gpt-4o"


class TestGetModelOrgScoped:
    """get_model() should resolve org-specific configs and tier-gate platform defaults."""

    @pytest_asyncio.fixture
    async def pro_org(self, db_session: AsyncSession) -> Organization:
        org = Organization(name="Pro Org", subscription_tier="pro")
        db_session.add(org)
        await db_session.flush()
        return org

    @pytest_asyncio.fixture
    async def essentials_org(self, db_session: AsyncSession) -> Organization:
        org = Organization(name="Essentials Org", subscription_tier="essentials")
        db_session.add(org)
        await db_session.flush()
        return org

    @pytest.mark.asyncio
    async def test_pro_org_gets_platform_default(
        self, db_session: AsyncSession, pro_org: Organization
    ):
        """Pro org with no custom config should get platform default."""
        model = await get_model("vision", db_session, org_id=pro_org.id)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3.2-vision"

    @pytest.mark.asyncio
    async def test_essentials_org_raises_without_custom_config(
        self, db_session: AsyncSession, essentials_org: Organization
    ):
        """Essentials org with no custom config should raise ValueError."""
        with pytest.raises(ValueError, match="not configured"):
            await get_model("vision", db_session, org_id=essentials_org.id)

    @pytest.mark.asyncio
    async def test_org_specific_config_takes_priority(
        self, db_session: AsyncSession, essentials_org: Organization
    ):
        """Org-specific config should work for any tier."""
        row = AiProviderConfig(
            org_id=essentials_org.id,
            capability="vision",
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            credentials={"api_key": "sk-test"},
            is_enabled=True,
        )
        db_session.add(row)
        await db_session.flush()

        model = await get_model("vision", db_session, org_id=essentials_org.id)
        assert model == "anthropic:claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_disabled_org_config_falls_through(
        self, db_session: AsyncSession, pro_org: Organization
    ):
        """Disabled org config should fall through to platform default for Pro."""
        row = AiProviderConfig(
            org_id=pro_org.id,
            capability="vision",
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            credentials={"api_key": "sk-test"},
            is_enabled=False,
        )
        db_session.add(row)
        await db_session.flush()

        model = await get_model("vision", db_session, org_id=pro_org.id)
        # Falls through to platform default since org config is disabled
        assert isinstance(model, OpenAIChatModel)

    @pytest.mark.asyncio
    async def test_no_org_id_raises(self, db_session: AsyncSession):
        """No org_id should raise ValueError (no config to fall back to)."""
        with pytest.raises(ValueError, match="not configured"):
            await get_model("vision", db_session, org_id=None)


class TestGetFullConfigOrgScoped:
    """get_full_config() should return org-specific or platform config."""

    @pytest_asyncio.fixture
    async def pro_org(self, db_session: AsyncSession) -> Organization:
        org = Organization(name="Pro Org", subscription_tier="pro")
        db_session.add(org)
        await db_session.flush()
        return org

    @pytest_asyncio.fixture
    async def essentials_org(self, db_session: AsyncSession) -> Organization:
        org = Organization(name="Essentials Org", subscription_tier="essentials")
        db_session.add(org)
        await db_session.flush()
        return org

    @pytest.mark.asyncio
    async def test_pro_gets_platform_config(
        self, db_session: AsyncSession, pro_org: Organization
    ):
        config = await get_full_config("vision", db_session, org_id=pro_org.id)
        assert config["provider"] == "ollama"
        assert config["is_enabled"] is True

    @pytest.mark.asyncio
    async def test_essentials_gets_not_configured(
        self, db_session: AsyncSession, essentials_org: Organization
    ):
        config = await get_full_config("vision", db_session, org_id=essentials_org.id)
        assert config["provider"] is None
        assert config["is_enabled"] is False

    @pytest.mark.asyncio
    async def test_org_config_returned(
        self, db_session: AsyncSession, essentials_org: Organization
    ):
        row = AiProviderConfig(
            org_id=essentials_org.id,
            capability="vision",
            provider="openai",
            model_name="gpt-4o",
            credentials={"api_key": "sk-test"},
            is_enabled=True,
        )
        db_session.add(row)
        await db_session.flush()

        config = await get_full_config("vision", db_session, org_id=essentials_org.id)
        assert config["provider"] == "openai"
        assert config["model_name"] == "gpt-4o"


class TestGetEnvFallback:
    """_get_env_fallback resolves credentials from provider-level Settings."""

    def test_returns_none_when_provider_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "")
        monkeypatch.setattr(settings, "ai_vision_model", "some-model")
        assert _get_env_fallback("vision") is None

    def test_returns_none_when_model_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "openrouter")
        monkeypatch.setattr(settings, "ai_vision_model", "")
        assert _get_env_fallback("vision") is None

    def test_resolves_api_key_from_provider_level(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "openrouter")
        monkeypatch.setattr(settings, "ai_vision_model", "anthropic/claude-sonnet-4")
        monkeypatch.setattr(
            settings,
            "openrouter",
            ProviderConfig(api_key="sk-or-test"),
        )
        result = _get_env_fallback("vision")
        assert result == {
            "provider": "openrouter",
            "model_name": "anthropic/claude-sonnet-4",
            "credentials": {"api_key": "sk-or-test"},
        }

    def test_resolves_base_url_for_ollama(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_chat_provider", "ollama")
        monkeypatch.setattr(settings, "ai_chat_model", "qwen3.5:27b")
        monkeypatch.setattr(
            settings,
            "ollama",
            ProviderConfig(base_url="http://lab-box:11434"),
        )
        result = _get_env_fallback("chat")
        assert result == {
            "provider": "ollama",
            "model_name": "qwen3.5:27b",
            "credentials": {"base_url": "http://lab-box:11434"},
        }

    def test_returns_none_credentials_when_provider_has_no_key(self, monkeypatch):
        """Ollama with no base_url is valid; credentials should be None."""
        monkeypatch.setattr(settings, "ai_text_provider", "ollama")
        monkeypatch.setattr(settings, "ai_text_model", "gemma3:latest")
        monkeypatch.setattr(settings, "ollama", ProviderConfig())
        result = _get_env_fallback("text")
        assert result == {
            "provider": "ollama",
            "model_name": "gemma3:latest",
            "credentials": None,
        }

    def test_unknown_provider_returns_none_credentials(self, monkeypatch):
        """A provider name not in the mapping still returns provider+model."""
        monkeypatch.setattr(settings, "ai_text_provider", "bedrock")
        monkeypatch.setattr(settings, "ai_text_model", "anthropic.claude")
        result = _get_env_fallback("text")
        assert result == {
            "provider": "bedrock",
            "model_name": "anthropic.claude",
            "credentials": None,
        }

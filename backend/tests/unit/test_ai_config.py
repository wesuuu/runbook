import time
import uuid

import pytest
import pytest_asyncio
from pydantic_ai.models.openai import OpenAIChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiProviderConfig
from app.services.ai_config import (
    _build_model_string,
    get_model,
    invalidate_cache,
    mask_api_key,
    _cache,
    _CACHE_TTL_SECONDS,
)


class TestBuildModelString:
    def test_ollama(self):
        result = _build_model_string("ollama", "llama3.2-vision")
        assert isinstance(result, OpenAIChatModel)
        assert result.model_name == "llama3.2-vision"

    def test_ollama_with_base_url(self):
        result = _build_model_string("ollama", "llama3.2-vision", base_url="http://myhost:11434")
        assert isinstance(result, OpenAIChatModel)

    def test_anthropic(self):
        assert _build_model_string("anthropic", "claude-sonnet-4-20250514") == "anthropic:claude-sonnet-4-20250514"

    def test_google(self):
        assert _build_model_string("google", "gemini-2.0-flash") == "google-gla:gemini-2.0-flash"

    def test_openai(self):
        assert _build_model_string("openai", "gpt-4o") == "openai:gpt-4o"


class TestMaskApiKey:
    def test_none(self):
        assert mask_api_key(None) is None

    def test_empty(self):
        assert mask_api_key("") is None

    def test_short_key(self):
        assert mask_api_key("abc123") == "ab...23"

    def test_long_key(self):
        result = mask_api_key("sk-ant-api03-abcdefghijklmnop")
        assert result == "sk-a...mnop"
        assert "abcdefgh" not in result

    def test_exactly_8_chars(self):
        result = mask_api_key("12345678")
        assert result == "12...78"


class TestGetModel:
    @pytest_asyncio.fixture(autouse=True)
    async def clear_cache(self):
        invalidate_cache()
        yield
        invalidate_cache()

    @pytest.mark.asyncio
    async def test_returns_hardcoded_default_when_no_db_or_env(
        self, db_session: AsyncSession
    ):
        model = await get_model("vision", db_session)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3.2-vision"

    @pytest.mark.asyncio
    async def test_db_row_takes_priority(self, db_session: AsyncSession):
        row = AiProviderConfig(
            capability="vision",
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            api_key="sk-test",
            is_enabled=True,
        )
        db_session.add(row)
        await db_session.flush()

        model = await get_model("vision", db_session)
        assert model == "anthropic:claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_disabled_row_falls_through_to_default(
        self, db_session: AsyncSession
    ):
        row = AiProviderConfig(
            capability="vision",
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            api_key="sk-test",
            is_enabled=False,
        )
        db_session.add(row)
        await db_session.flush()

        model = await get_model("vision", db_session)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3.2-vision"

    @pytest.mark.asyncio
    async def test_cache_returns_cached_value(self, db_session: AsyncSession):
        # Prime cache
        await get_model("vision", db_session)
        assert "vision" in _cache

        # Insert a DB row — should NOT affect cached result
        row = AiProviderConfig(
            capability="vision",
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-test",
            is_enabled=True,
        )
        db_session.add(row)
        await db_session.flush()

        # Still returns cached default (Ollama model object)
        model = await get_model("vision", db_session)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3.2-vision"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, db_session: AsyncSession):
        # Prime cache with default
        await get_model("vision", db_session)

        # Insert a DB row
        row = AiProviderConfig(
            capability="vision",
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-test",
            is_enabled=True,
        )
        db_session.add(row)
        await db_session.flush()

        # Invalidate and re-fetch
        invalidate_cache("vision")
        model = await get_model("vision", db_session)
        assert model == "openai:gpt-4o"

    @pytest.mark.asyncio
    async def test_invalidate_all(self, db_session: AsyncSession):
        await get_model("vision", db_session)
        await get_model("text", db_session)
        assert "vision" in _cache
        assert "text" in _cache

        invalidate_cache()
        assert len(_cache) == 0

    @pytest.mark.asyncio
    async def test_unknown_capability_falls_back_to_text_default(
        self, db_session: AsyncSession
    ):
        model = await get_model("unknown_capability", db_session)
        # Falls back to text defaults (Ollama model object)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3.2"

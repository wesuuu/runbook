import time
from typing import Optional, Union

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai import (
    AiProviderConfig,
    DEFAULT_CONFIGS,
    SUPPORTED_PROVIDERS,
)

ModelType = Union[str, OpenAIChatModel]

# In-memory cache: capability -> (model, fetched_at)
_cache: dict[str, tuple[ModelType, float]] = {}
_CACHE_TTL_SECONDS = 30.0


def invalidate_cache(capability: Optional[str] = None):
    if capability:
        _cache.pop(capability, None)
    else:
        _cache.clear()


def _build_model_string(provider: str, model_name: str, base_url: Optional[str] = None) -> ModelType:
    """Build a pydantic-ai model identifier from provider + model.

    For Ollama, returns an OpenAIModel with an OllamaProvider so
    the base_url is passed through (pydantic-ai requires
    OLLAMA_BASE_URL env var otherwise).
    For other providers, returns a string like 'anthropic:model_name'.
    """
    if provider == "ollama":
        ollama_base = base_url or "http://localhost:11434"
        if not ollama_base.rstrip("/").endswith("/v1"):
            ollama_base = ollama_base.rstrip("/") + "/v1"
        return OpenAIChatModel(
            model_name=model_name,
            provider=OllamaProvider(base_url=ollama_base),
        )
    prefix_map = {
        "anthropic": "anthropic",
        "google": "google-gla",
        "openai": "openai",
    }
    prefix = prefix_map.get(provider, provider)
    return f"{prefix}:{model_name}"


def _get_env_fallback(capability: str) -> Optional[tuple[str, str, Optional[str], Optional[str]]]:
    """Check env vars for a capability config.

    Returns (provider, model_name, api_key, base_url) or None.
    """
    prefix = f"ai_{capability}_"
    provider = getattr(settings, f"{prefix}provider", None)
    model_name = getattr(settings, f"{prefix}model", None)
    if provider and model_name:
        api_key = getattr(settings, f"{prefix}api_key", None)
        base_url = getattr(settings, f"{prefix}base_url", None)
        return (provider, model_name, api_key, base_url)
    return None


def mask_api_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return key[:2] + "..." + key[-2:]
    return key[:4] + "..." + key[-4:]


async def get_model(capability: str, db: AsyncSession) -> ModelType:
    """Resolve the pydantic-ai model for a capability.

    Resolution order:
    1. In-memory cache (if fresh)
    2. DB row for capability
    3. Env var fallback
    4. Hardcoded default
    """
    now = time.monotonic()
    cached = _cache.get(capability)
    if cached:
        model, fetched_at = cached
        if now - fetched_at < _CACHE_TTL_SECONDS:
            return model

    # 1. Try DB
    result = await db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == capability,
            AiProviderConfig.is_enabled == True,
        )
    )
    row = result.scalar_one_or_none()

    if row:
        model = _build_model_string(row.provider, row.model_name, row.base_url)
        _cache[capability] = (model, now)
        return model

    # 2. Try env var fallback
    env = _get_env_fallback(capability)
    if env:
        provider, model_name, _, base_url = env
        model = _build_model_string(provider, model_name, base_url)
        _cache[capability] = (model, now)
        return model

    # 3. Hardcoded default
    defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
    model = _build_model_string(defaults["provider"], defaults["model_name"])
    _cache[capability] = (model, now)
    return model


async def get_api_key(capability: str, db: AsyncSession) -> Optional[str]:
    """Get the API key for a capability (needed for cloud providers)."""
    result = await db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == capability,
        )
    )
    row = result.scalar_one_or_none()
    if row and row.api_key:
        return row.api_key

    env = _get_env_fallback(capability)
    if env:
        return env[2]  # api_key

    return None


async def get_full_config(
    capability: str, db: AsyncSession
) -> dict:
    """Get the full resolved config dict for a capability."""
    result = await db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == capability,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return {
            "provider": row.provider,
            "model_name": row.model_name,
            "api_key": row.api_key,
            "base_url": row.base_url,
            "is_enabled": row.is_enabled,
        }

    env = _get_env_fallback(capability)
    if env:
        provider, model_name, api_key, base_url = env
        return {
            "provider": provider,
            "model_name": model_name,
            "api_key": api_key,
            "base_url": base_url,
            "is_enabled": True,
        }

    defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
    return {
        "provider": defaults["provider"],
        "model_name": defaults["model_name"],
        "api_key": None,
        "base_url": None,
        "is_enabled": True,
    }

from typing import Optional, Union
from uuid import UUID

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
from app.models.iam import Organization, SubscriptionTier, TIER_RANK

ModelType = Union[str, OpenAIChatModel]


def _build_model_string(
    provider: str, model_name: str, credentials: dict | None = None
) -> ModelType:
    """Build a pydantic-ai model identifier from provider + model.

    For Ollama, returns an OpenAIModel with an OllamaProvider so
    the base_url is passed through.
    For other providers, returns a string like 'anthropic:model_name'.
    """
    if provider == "ollama":
        creds = credentials or {}
        ollama_base = creds.get("base_url") or "http://localhost:11434"
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
        "groq": "groq",
        "mistral": "mistral",
        "cohere": "cohere",
        "openrouter": "openrouter",
        "xai": "xai",
        "cerebras": "cerebras",
        "deepseek": "deepseek",
        "together": "together",
        "fireworks": "fireworks",
        "bedrock": "bedrock",
    }
    prefix = prefix_map.get(provider, provider)
    return f"{prefix}:{model_name}"


def _get_env_fallback(capability: str) -> dict | None:
    """Check env vars for a capability config.

    Returns a config dict or None.
    """
    prefix = f"ai_{capability}_"
    provider = getattr(settings, f"{prefix}provider", None)
    model_name = getattr(settings, f"{prefix}model", None)
    if provider and model_name:
        api_key = getattr(settings, f"{prefix}api_key", None)
        base_url = getattr(settings, f"{prefix}base_url", None)
        creds = {}
        if api_key:
            creds["api_key"] = api_key
        if base_url:
            creds["base_url"] = base_url
        return {
            "provider": provider,
            "model_name": model_name,
            "credentials": creds or None,
        }
    return None


async def _is_org_pro_or_above(org_id: Optional[UUID], db: AsyncSession) -> bool:
    """Check if an org has Pro tier or above."""
    if org_id is None:
        return False
    result = await db.execute(
        select(Organization.subscription_tier).where(Organization.id == org_id)
    )
    tier_str = result.scalar_one_or_none()
    if tier_str is None:
        return False
    try:
        tier = SubscriptionTier(tier_str)
    except ValueError:
        return False
    return TIER_RANK[tier] >= TIER_RANK[SubscriptionTier.PRO]


async def get_model(
    capability: str, db: AsyncSession, org_id: Optional[UUID] = None
) -> ModelType:
    """Resolve the pydantic-ai model for a capability.

    Resolution order:
    1. Org-specific DB row (any tier)
    2. Platform config from env vars (Pro+ only)
    3. Hardcoded default (Pro+ only)

    Raises ValueError if the org has no config and is not Pro+.
    """
    # 1. Try org-specific DB row
    if org_id is not None:
        result = await db.execute(
            select(AiProviderConfig).where(
                AiProviderConfig.org_id == org_id,
                AiProviderConfig.capability == capability,
                AiProviderConfig.is_enabled == True,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return _build_model_string(row.provider, row.model_name, row.credentials)

    # 2. Tier gate: only Pro+ can use platform config
    is_pro = await _is_org_pro_or_above(org_id, db)

    if is_pro:
        env = _get_env_fallback(capability)
        if env:
            return _build_model_string(
                env["provider"], env["model_name"], env["credentials"]
            )

        defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
        return _build_model_string(defaults["provider"], defaults["model_name"])

    raise ValueError(
        f"AI capability '{capability}' is not configured. "
        "Add your own AI provider in Settings, or upgrade to Pro."
    )


async def get_credentials(
    capability: str, db: AsyncSession, org_id: Optional[UUID] = None
) -> dict | None:
    """Get the credentials dict for a capability."""
    # 1. Try org-specific row
    if org_id is not None:
        result = await db.execute(
            select(AiProviderConfig).where(
                AiProviderConfig.org_id == org_id,
                AiProviderConfig.capability == capability,
            )
        )
        row = result.scalar_one_or_none()
        if row and row.credentials:
            return row.credentials

    # 2. Env var fallback (Pro+ only)
    is_pro = await _is_org_pro_or_above(org_id, db)
    if is_pro:
        env = _get_env_fallback(capability)
        if env:
            return env["credentials"]

    return None


async def get_full_config(
    capability: str, db: AsyncSession, org_id: Optional[UUID] = None
) -> dict:
    """Get the full resolved config dict for a capability."""
    # 1. Try org-specific row
    if org_id is not None:
        result = await db.execute(
            select(AiProviderConfig).where(
                AiProviderConfig.org_id == org_id,
                AiProviderConfig.capability == capability,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return {
                "provider": row.provider,
                "model_name": row.model_name,
                "credentials": row.credentials,
                "is_enabled": row.is_enabled,
            }

    # 2. Env var fallback (Pro+ only)
    is_pro = await _is_org_pro_or_above(org_id, db)
    if is_pro:
        env = _get_env_fallback(capability)
        if env:
            return {
                "provider": env["provider"],
                "model_name": env["model_name"],
                "credentials": env["credentials"],
                "is_enabled": True,
            }

        defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
        return {
            "provider": defaults["provider"],
            "model_name": defaults["model_name"],
            "credentials": None,
            "is_enabled": True,
        }

    # Not configured
    return {
        "provider": None,
        "model_name": None,
        "credentials": None,
        "is_enabled": False,
    }

from typing import Optional, Union
from uuid import UUID

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai import (DEFAULT_CONFIGS, SUPPORTED_PROVIDERS,
                           AiProviderConfig)
from app.models.iam import TIER_RANK, Organization, SubscriptionTier

ModelType = Union[str, OpenAIChatModel]


# Map provider name → env var that pydantic-ai reads for the API key
_PROVIDER_ENV_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}

# Map provider name → attribute name on Settings holding its ProviderConfig.
# Identity-mapped today; kept as a dict so provider names that don't match
# their Settings attribute (e.g. `google_vertex` serving provider `google`)
# can diverge later without touching _get_env_fallback. Add a new entry
# whenever a new ProviderConfig field is added to Settings.
_PROVIDER_SETTINGS_ATTRS: dict[str, str] = {
    "openrouter": "openrouter",
    "ollama": "ollama",
}


def _build_model_string(
    provider: str, model_name: str, credentials: dict | None = None
) -> ModelType:
    """Build a pydantic-ai model identifier from provider + model.

    For Ollama, returns an OpenAIModel with an OllamaProvider so
    the base_url is passed through.
    For other providers, returns a string like 'anthropic:model_name'.

    If credentials include an api_key, it is injected into os.environ
    under the standard env var name that pydantic-ai expects (e.g.,
    OPENROUTER_API_KEY). This bridges the gap between Batchrite's
    config system (BATCHRITE_<PROVIDER>__API_KEY) and pydantic-ai.
    """
    import os

    if provider == "ollama":
        creds = credentials or {}
        ollama_base = creds.get("base_url") or "http://localhost:11434"
        if not ollama_base.rstrip("/").endswith("/v1"):
            ollama_base = ollama_base.rstrip("/") + "/v1"
        return OpenAIChatModel(
            model_name=model_name,
            provider=OllamaProvider(base_url=ollama_base),
        )

    # Inject API key into os.environ if provided via credentials
    # (from DB config or BATCHRITE_<PROVIDER>__API_KEY env vars)
    if credentials and credentials.get("api_key"):
        env_key = _PROVIDER_ENV_KEYS.get(provider)
        if env_key and not os.environ.get(env_key):
            os.environ[env_key] = credentials["api_key"]

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

    Reads ``ai_{capability}_provider`` + ``ai_{capability}_model`` from settings,
    then looks up credentials on the provider-level ProviderConfig
    (``settings.<provider>.api_key`` / ``.base_url``).

    Returns a config dict or None.
    """
    provider = getattr(settings, f"ai_{capability}_provider", "")
    model_name = getattr(settings, f"ai_{capability}_model", "")
    if not (provider and model_name):
        return None

    creds: dict[str, str] = {}
    attr = _PROVIDER_SETTINGS_ATTRS.get(provider)
    if attr is not None:
        pc = getattr(settings, attr)
        if pc.api_key:
            creds["api_key"] = pc.api_key
        if pc.base_url:
            creds["base_url"] = pc.base_url

    return {
        "provider": provider,
        "model_name": model_name,
        "credentials": creds or None,
    }


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


def _resolve_context_window_from_name(model_name: str) -> int | None:
    """Match a model name against settings.context_window_defaults.

    Tries exact match first, then prefix match (longest prefix wins).
    """
    defaults = settings.context_window_defaults
    if model_name in defaults:
        return defaults[model_name]
    # Prefix match — longest key that matches wins
    best_key = ""
    for key in defaults:
        if model_name.startswith(key) and len(key) > len(best_key):
            best_key = key
    if best_key:
        return defaults[best_key]
    return None


async def get_context_window(
    capability: str, db: AsyncSession, org_id: Optional[UUID] = None
) -> int:
    """Resolve the context window size for a capability.

    Resolution order:
    1. AiProviderConfig.context_window from DB
    2. settings.context_window_defaults lookup by model name
    3. 8192 fallback
    """
    model_name = None

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
            if row.context_window:
                return row.context_window
            model_name = row.model_name

    # 2. Env var / default model name lookup
    if model_name is None:
        env = _get_env_fallback(capability)
        if env:
            model_name = env["model_name"]
        else:
            defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
            model_name = defaults["model_name"]

    if model_name:
        from_config = _resolve_context_window_from_name(model_name)
        if from_config is not None:
            return from_config

    # 3. Conservative fallback
    return 8192


async def get_model_display_name(
    capability: str, db: AsyncSession, org_id: Optional[UUID] = None
) -> str:
    """Return a human-readable model name for a capability."""
    if org_id is not None:
        result = await db.execute(
            select(AiProviderConfig.model_name).where(
                AiProviderConfig.org_id == org_id,
                AiProviderConfig.capability == capability,
                AiProviderConfig.is_enabled == True,
            )
        )
        name = result.scalar_one_or_none()
        if name:
            return name

    env = _get_env_fallback(capability)
    if env:
        return env["model_name"]

    defaults = DEFAULT_CONFIGS.get(capability, DEFAULT_CONFIGS["text"])
    return defaults["model_name"]
